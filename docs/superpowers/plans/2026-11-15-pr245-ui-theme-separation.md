# Overall Office UI Theme Separation

Direct user instructions: separate the overall UI theme, faithfully copy GenOffice UI, remove toolbars, no user model chooser.

- [ ] Copy pinned GenOffice UI tokens with hash/license, scope light/dark/system selectors to Office UI and keep document content independent.
- [ ] Move palette and preference theme overrides to office-ui-theme.css; structural and business modules consume tokens.
- [ ] Remove the legacy smart-report toolbar; retain all four Office ribbons and their existing authorized commands.
- [ ] Separate assistant theme aliases against source tokens without changing controllers.
- [ ] Run scoped tests, independent review, build/budget and actual browser screenshots; sync PR245 without force.
