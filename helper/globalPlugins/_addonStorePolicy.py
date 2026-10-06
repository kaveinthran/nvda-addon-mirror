"""Source-aware routing for NVDA's shared Add-on Store metadata manager."""

from __future__ import annotations

import contextlib
import contextvars
import json
import os
import threading
from urllib.parse import urlparse


OFFICIAL = ""
MIRROR = "https://serrebidev.github.io/nvda-addon-mirror"
_source = contextvars.ContextVar("serrebiAddonStoreSource", default=None)


def validCustomURL(value):
	if not isinstance(value, str) or any(ord(char) < 32 for char in value):
		return None
	parsed = urlparse(value.strip())
	try:
		port = parsed.port
	except ValueError:
		return None
	if (
		parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
		or parsed.query or parsed.fragment or (port is not None and not 1 <= port <= 65535)
	):
		return None
	return value.strip().rstrip("/")


def selectedURL(settings):
	policy = settings.get("storePolicy", "mirror")
	if policy == "official":
		return OFFICIAL
	if policy == "original":
		return settings.get("originalStoreURL", "")
	if policy == "custom":
		return validCustomURL(settings.get("customStoreURL", "")) or MIRROR
	return MIRROR


class Router:
	"""Serialize core metadata calls and retain separate in-memory caches per source."""
	def __init__(self, defaultURL):
		self.defaultURL = defaultURL
		self.lock = threading.RLock()
		self.caches = {}
		self.patches = []
		self.generation = 0

	@contextlib.contextmanager
	def source(self, url):
		token = _source.set(url)
		try:
			yield
		finally:
			_source.reset(token)

	def currentURL(self):
		return _source.get() if _source.get() is not None else self.defaultURL

	def install(self, network, dataManager, storeModule, patch):
		originalBaseURL = network._getBaseURL
		patch(network, "_getBaseURL", lambda: self.currentURL() or originalBaseURL())
		for name in ("getLatestCompatibleAddons", "getLatestAddons"):
			original = getattr(dataManager._DataManager, name)
			def fetch(manager, *args, _original=original, **kwargs):
				url = self.currentURL()
				with self.lock:
					with self.source(url):
						self._activate(manager, url)
						result = _original(manager, *args, **kwargs)
						self._remember(manager, url)
						return result
			patch(dataManager._DataManager, name, fetch)
		for name in ("_cacheCompatibleAddons", "_cacheLatestAddons"):
			original = getattr(dataManager._DataManager, name)
			def cache(manager, *args, _original=original, _name=name, **kwargs):
				path = manager._cacheCompatibleFile if _name == "_cacheCompatibleAddons" else manager._cacheLatestFile
				before = self._fileStamp(path)
				result = _original(manager, *args, **kwargs)
				if args and len(args) > 1 and args[0] and args[1] and before != self._fileStamp(path):
					self._markCacheFile(path)
				return result
			patch(dataManager._DataManager, name, cache)
		originalCached = dataManager._DataManager._getCachedAddonData
		def getCached(manager, path, *args, **kwargs):
			try:
				with open(path, "r", encoding="utf-8") as file:
					if json.load(file).get("serrebiStoreSource") != self.currentURL():
						return None
			except (OSError, ValueError):
				return None
			return originalCached(manager, path, *args, **kwargs)
		patch(dataManager._DataManager, "_getCachedAddonData", getCached)
		originalInit = storeModule.AddonStoreVM.__init__
		def init(vm, *args, **kwargs):
			vm._serrebiStoreURL = self.currentURL()
			return originalInit(vm, *args, **kwargs)
		patch(storeModule.AddonStoreVM, "__init__", init)
		originalFetch = storeModule.AddonStoreVM._getAvailableAddonsInBG
		def fetchAvailable(vm, *args, **kwargs):
			with self.source(getattr(vm, "_serrebiStoreURL", self.defaultURL)):
				return originalFetch(vm, *args, **kwargs)
		patch(storeModule.AddonStoreVM, "_getAvailableAddonsInBG", fetchAvailable)

	def _activate(self, manager, url):
		state = self.caches.get(url)
		if state is None:
			with self.source(url):
				state = (
					manager._getCachedAddonData(manager._cacheLatestFile),
					manager._getCachedAddonData(manager._cacheCompatibleFile),
				)
			self.caches[url] = state
		manager._latestAddonCache, manager._compatibleAddonCache = state

	def _remember(self, manager, url):
		self.caches[url] = (manager._latestAddonCache, manager._compatibleAddonCache)

	def _fileStamp(self, path):
		try:
			return os.stat(path).st_mtime_ns
		except OSError:
			return None

	def _markCacheFile(self, path):
		try:
			with open(path, "r", encoding="utf-8") as file:
				data = json.load(file)
			data["serrebiStoreSource"] = self.currentURL()
			with open(path, "w", encoding="utf-8") as file:
				json.dump(data, file, ensure_ascii=False)
		except (OSError, ValueError):
			return
