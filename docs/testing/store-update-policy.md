# Store and update policy test guide

1. Open NVDA Settings, SerrebiRadio add-on store. Choose Mirror, Official,
   Original store, then a valid Custom HTTPS URL. Restart NVDA after each
   choice and confirm the regular Add-on Store and future update checks use the
   selected source. Check that HTTP, credentials, and malformed custom URLs are
   refused.
2. In NVDA Settings, Add-on Store, select each native Automatic updates value:
   Notify, Update, and Disabled. Confirm the selected core value remains after
   restart. Changing the source must not install an already pending update.
3. Open Tools, Add-on Store, Official NVDA store. Close it with Close and with
   Escape. Confirm the regular store returns to the chosen default source in
   each case. While the temporary official view is open, refresh it and confirm
   a simultaneous automatic update check still uses the chosen default source.
4. Change sources after metadata was fetched. Confirm that add-ons from the
   previous source do not appear until fetched from the new source. Restart and
   repeat to confirm source-marked caches are not reused across sources.
5. On the secure desktop, confirm no policy routing or custom source action is
   available.

Automated checks cover policy URL selection, HTTPS validation, and isolated
per-source in-memory cache state. Live source routing, native settings speech,
automatic-update behavior, and cache files across restart remain not checked.
