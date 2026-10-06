# Discovery and repository access test guide

Use this guide with an experimental helper package only. Do not publish it or
clone repositories containing material you do not trust.

1. Open the mirror Add-on Store and select an add-on with an author or publisher.
   Open its context menu with Applications or Shift+F10. Confirm **More by
   author** opens a keyboard-readable results window. The selected add-on may
   be the sole result; in that case confirm it says the result is limited to
   the loaded catalog. Where another channel for the same add-on exists, it
   must not be counted twice. Check that author/publisher and repository-owner
   matches are named separately.
2. Select an add-on with meaningful name and description text. Use **More like
   this** and confirm the results omit the selected add-on, give match reasons
   (title or description tokens), and remain in the same order when reopened.
   Try a specialized add-on whose words are not shared and confirm the clear
   no-results message.
3. On an installed add-on, check **Open installed folder** opens that add-on's
   resolved folder. It must not appear for a catalog-only or unavailable
   installed path.
4. On an add-on whose source is a plain `https://github.com/owner/repository`
   URL, confirm **Open repository page** and **Clone repository...** appear.
   Verify these actions do not appear for HTTP, non-GitHub, credentialed, or
   subpage source URLs.
5. Choose **Clone repository...**, select a parent folder you control, and
   wait for the spoken completion message. Confirm the new child folder has the
   repository name and contains a normal Git checkout. Choose the same parent
   again and confirm the existing target is refused without replacement.
6. Start a clone, then close NVDA before it finishes. Confirm no late success
   or failure message is spoken after termination. Repeat all actions on the
   secure desktop and confirm they are unavailable.

Automated checks cover URL rejection, channel de-duplication, deterministic
weighted matching, match explanations, argument-vector cloning, existing-path
refusal, and sanitized Git failures. Live speech, braille, focus behavior,
secure-desktop behavior, and actual cloning are still not checked.
