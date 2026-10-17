# Componente vizuale

Designul integrează componentele din cele două prompturi 21st.dev furnizate de utilizator:

- `BranchingReasoningChatInput`, adaptat în `src/components/ui/branching-reasoning-chat-input.tsx`. Demo-ul cu timere și scoruri ilustrative nu este inclus. Cardurile folosesc numai `attempts` din API; conversația și formularul sunt conectate la implementarea existentă.
- `SculptureHero` / `liquid-sculpture-hero`, atribuit în sursa furnizată lui **guglielmogiannattasio.it**. Motorul WebGL și fallback-ul static sunt păstrate. CSS-ul este extras într-un fișier pentru compatibilitate cu CSP; fonturile Google nu sunt încărcate la runtime.

Cele patru imagini din promptul SculptureHero au fost copiate din URL-urile `cdn.21st.dev/assets/mirror/` în `public/sculpture/form-0.webp` până la `form-3.webp`, în ordinea light, dark, mobile light, mobile dark. Sunt servite local. Atribuirea originală este păstrată în cod și în acest document; aici nu se atribuie o licență nouă componentelor sau imaginilor furnizate.

Fonturile Geist și Instrument Serif sunt distribuite local prin pachetele `@fontsource`, care includ informațiile lor de licență.

## Workspace background
Skylight Fish Swarm — GetLayers, selected from the free gallery by the user.
Source: https://www.getlayers.ai/backgrounds?tier=free&layer=skylight-fish-swarm
Downloaded 2026-10-18 from the displayed media. The gallery labels it free for
commercial use. The supplied watermark is retained. Files in public/backgrounds/.
Served locally, with pause and reduced-motion fallback.
