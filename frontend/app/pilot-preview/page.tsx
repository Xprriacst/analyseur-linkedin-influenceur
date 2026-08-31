"use client";

import { useState } from "react";
import PilotModeView, { type PilotPlan } from "../components/pilot/PilotModeView";

/** Données fictives pour la maquette produit — remplacées par GET /me/pilot/today en prod. */
const MOCK_PLAN: PilotPlan = {
  userName: "Alex",
  dayNumber: 3,
  weekNumber: 1,
  weeklyDone: 2,
  weeklyTotal: 3,
  post: {
    structure: "Histoire → leçon → CTA",
    hook: "Il y a 6 mois, je pensais que poster sur LinkedIn était une perte de temps.",
    body: `Puis j'ai testé une chose simple : parler de ce que je vivais vraiment en tant que builder — pas de conseils génériques.

Résultat en 90 jours : des conversations avec des fondateurs qui avaient exactement mon ICP. Pas des vanity metrics.

Si tu es en train de lancer ton offre B2B et que tu postes dans le vide, commence par une histoire vécue cette semaine. Une seule. Et termine par une question sincère.`,
  },
  contacts: [
    {
      id: "1",
      name: "Marie Dupont",
      role: "Fondatrice SaaS RH",
      company: "TalentFlow",
      score: 92,
      initials: "MD",
      accent: "linear-gradient(135deg, #6366f1, #4338ca)",
      message:
        "Bonjour Marie — j'ai vu ton post sur le recrutement en hypercroissance. On cible les mêmes profils fondateurs. Curieux d'échanger 15 min sur ce qui marche côté contenu ?",
    },
    {
      id: "2",
      name: "Thomas Leroy",
      role: "Consultant B2B",
      company: "Indépendant",
      score: 78,
      initials: "TL",
      accent: "linear-gradient(135deg, #0ea5e9, #0369a1)",
      message:
        "Salut Thomas — ton angle « vendre sans être pushy » résonne avec ce qu'on fait chez les builders SaaS. Je partage des retours terrain chaque semaine, ça pourrait t'intéresser.",
    },
    {
      id: "3",
      name: "Léa Rousseau",
      role: "Head of Growth",
      company: "ScaleUp Studio",
      score: 85,
      initials: "LR",
      accent: "linear-gradient(135deg, #10b981, #047857)",
      message:
        "Hello Léa — ton contenu sur l'acquisition organique m'a parlé. Je monte une offre pour les fondateurs early-stage — un échange rapide pour comparer nos approches ?",
    },
  ],
  strategy: {
    profiles: ["@romain-cornille", "@flora-codaccioni"],
    frequency: "3 posts / semaine · mardi, jeudi, samedi",
    target: "Fondateurs SaaS B2B · 10–50 employés · France",
    structureHint: "Récit personnel + insight actionnable + question ouverte",
  },
};

export default function PilotPreviewPage() {
  const [mode, setMode] = useState<"pilot" | "expert">("pilot");

  return (
    <PilotModeView
      plan={MOCK_PLAN}
      preview
      mode={mode}
      onModeChange={setMode}
    />
  );
}
