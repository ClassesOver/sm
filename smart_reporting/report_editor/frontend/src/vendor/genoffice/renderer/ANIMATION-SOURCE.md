Animation Preview source migration

Pinned source commit: f8c17004fb730df11f0f743164ffd8b4281bb38c. See ANIMATION-SOURCE.json for byte identities and exact adaptations.

`animation-play.ts` preserves all pinned runtime code; `AnimatedSlide.tsx` preserves useAnimPlayer, AnimatedSlideStage, paragraph clipping, effect transforms and the 350ms/600ms preview schedule. Only imports, the localized hint, and an optional host-fit width are adapted. The host adds focus/resize/exit disposal around that component; source/draft identity conversion and warnings are separate host code. No write protocol is added.

Unsupported source preset XML is kept in the file and explicitly skipped in the preview. Media commands are not executed: the pinned Preview itself does not consume mediaCmds, and native render-tree only supplies image URLs, not audio/video resources. This migration does not claim full SlideShow playback, all effect fidelity, or media execution.
