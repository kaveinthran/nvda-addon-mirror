import importlib.util
import os
import pathlib
import subprocess
import unittest
from types import SimpleNamespace
from unittest import mock


_PATH = pathlib.Path(__file__).parents[1] / "helper" / "globalPlugins" / "_addonStoreDiscovery.py"
_SPEC = importlib.util.spec_from_file_location("discovery", _PATH)
discovery = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(discovery)


def model(addonId, name, description="", author=None, publisher=None, sourceURL=""):
	return SimpleNamespace(
		addonId=addonId, displayName=name, description=description, author=author,
		publisher=publisher, sourceURL=sourceURL,
	)


class DiscoveryTests(unittest.TestCase):
	def test_author_matches_deduplicate_channels_and_separate_evidence(self):
		selected = model("one", "One", author="Ada", sourceURL="https://github.com/Ada/tools")
		matches = discovery.authorMatches(selected, [
			selected,
			model("two", "Two", publisher="ada"),
			model("two", "Two dev", publisher="Ada"),
			model("three", "Three", sourceURL="https://github.com/ada/other"),
		])
		self.assertEqual(["one", "two", "three"], [item[0].addonId for item in matches])
		self.assertEqual(("author/publisher",), matches[1][1])
		self.assertEqual(("repository owner",), matches[2][1])

	def test_similarity_is_weighted_excludes_self_and_explains_match(self):
		selected = model("one", "Network Tools", "Manage network profiles")
		matches = discovery.similarMatches(selected, [
			selected,
			model("two", "Network Manager", "Profiles and settings"),
			model("three", "Profiles", "Manage network profiles"),
		])
		self.assertEqual(["two", "three"], [item[0].addonId for item in matches])
		self.assertIn("title: network", matches[0][1])
		self.assertIn("description: manage, network, profiles", matches[1][1])

	def test_repository_accepts_only_plain_https_github_repo(self):
		self.assertEqual(("owner", "repo"), discovery.githubRepository("https://github.com/Owner/repo.git"))
		self.assertIsNone(discovery.githubRepository("http://github.com/owner/repo"))
		self.assertIsNone(discovery.githubRepository("https://github.com/owner/repo/issues"))
		self.assertIsNone(discovery.githubRepository("https://user@github.com/owner/repo"))
		for suffix in ("?download=1", "#fragment"):
			self.assertIsNone(discovery.githubRepository("https://github.com/owner/repo" + suffix))
		self.assertIsNone(discovery.githubRepository("https://github.com:444/owner/repo"))
		self.assertIsNone(discovery.githubRepository("https://github.com:invalid/owner/repo"))

	def test_missing_author_identity_has_no_invented_matches(self):
		selected = model("one", "One")
		self.assertEqual([], discovery.authorMatches(selected, [selected, model("two", "Two")]))

	def test_clone_uses_argument_vector_and_refuses_existing_destination(self):
		with mock.patch.object(discovery.subprocess, "run") as run:
			run.return_value = SimpleNamespace(returncode=0)
			result = discovery.cloneRepository("https://github.com/owner/repo", "G:\\new-repo")
		self.assertEqual("G:\\new-repo", result)
		self.assertEqual(
			["git", "clone", "--", "https://github.com/owner/repo", "G:\\new-repo"],
			run.call_args.args[0],
		)
		with mock.patch.object(discovery.os.path, "exists", return_value=True):
			with self.assertRaises(ValueError):
				discovery.cloneRepository("https://github.com/owner/repo", "G:\\new-repo")

	def test_clone_sanitizes_git_failure(self):
		with mock.patch.object(discovery.subprocess, "run", return_value=SimpleNamespace(returncode=1)):
			with self.assertRaisesRegex(RuntimeError, "could not clone"):
				discovery.cloneRepository("https://github.com/owner/repo", "G:\\new-repo")


if __name__ == "__main__":
	unittest.main()
