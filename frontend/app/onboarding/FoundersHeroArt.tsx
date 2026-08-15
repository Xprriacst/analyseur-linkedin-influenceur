/**
 * Illustration au trait du hero /onboarding — patron Catalog (ligne noire,
 * scène de bureau). Un builder devant son LinkedIn pendant que
 * le pipeline avance tout seul.
 */
export default function FoundersHeroArt() {
  return (
    <svg
      className="fl-art"
      viewBox="0 0 420 200"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      {/* Bureau */}
      <path d="M28 168 H392" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      <path d="M52 168 V188" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      <path d="M368 168 V188" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />

      {/* Écran / fenêtre LinkedIn */}
      <rect x="48" y="38" width="168" height="118" rx="10" stroke="currentColor" strokeWidth="2" />
      <path d="M48 58 H216" stroke="currentColor" strokeWidth="2" />
      <circle cx="62" cy="48" r="3" fill="currentColor" />
      <circle cx="74" cy="48" r="3" fill="currentColor" />
      <circle cx="86" cy="48" r="3" fill="currentColor" />

      {/* Avatar + post */}
      <circle cx="78" cy="82" r="12" stroke="currentColor" strokeWidth="2" />
      <path d="M98 76 H178" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      <path d="M98 88 H158" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      <rect x="66" y="104" width="132" height="36" rx="6" stroke="currentColor" strokeWidth="2" />
      <path d="M78 116 H186" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" opacity=".55" />
      <path d="M78 126 H160" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" opacity=".55" />

      {/* Courbe de pipeline qui monte */}
      <path
        d="M250 142 C270 138, 278 120, 292 108 C306 96, 318 92, 338 78 C350 70, 362 58, 378 48"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
      <circle cx="378" cy="48" r="5" fill="currentColor" />
      <path d="M250 142 H378" stroke="currentColor" strokeWidth="1.5" opacity=".35" />
      <path d="M250 142 V70" stroke="currentColor" strokeWidth="1.5" opacity=".35" />

      {/* Petites pastilles « leads » */}
      <circle cx="292" cy="108" r="3.5" fill="currentColor" />
      <circle cx="318" cy="92" r="3.5" fill="currentColor" />
      <circle cx="346" cy="72" r="3.5" fill="currentColor" />

      {/* Personnage assis (simplifié) */}
      <circle cx="248" cy="118" r="11" stroke="currentColor" strokeWidth="2" />
      <path
        d="M248 129 C236 132, 228 142, 226 156 H270 C268 142, 260 132, 248 129 Z"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinejoin="round"
      />
      <path d="M236 146 H220" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}
