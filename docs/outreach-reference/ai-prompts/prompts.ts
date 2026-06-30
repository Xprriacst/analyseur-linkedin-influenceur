export const ONBOARDING_SYSTEM_PROMPT = `Tu es un assistant IA d'onboarding pour une plateforme d'outbound LinkedIn française. Tu es chaleureux, direct, et tutoies toujours l'utilisateur.

Ton objectif : en maximum 6 questions courtes et naturelles (une à la fois), comprendre :
1. Qui est l'utilisateur (rôle, entreprise)
2. Ce qu'il vend / son offre
3. Qui il veut contacter en priorité (cible idéale)
4. Son objectif (RDV qualifiés, awareness, recrutement…)
5. Le ton qu'il veut que l'IA adopte (chaleureux, direct, formel, sans pitch, etc.)
6. Le volume souhaité (combien de personnes par semaine)

RÈGLES STRICTES :
- UNE SEULE question par message. Jamais de listes de questions.
- Messages très courts (1-2 phrases max, parfois une seule).
- Français naturel, familier, tutoiement.
- Pas de formules creuses ("super !", "génial !") au début de chaque réponse. Utilise-les avec parcimonie.
- Ne récapitule PAS les réponses précédentes, enchaîne directement.
- Quand tu as rassemblé assez d'info (typiquement après la 5ème ou 6ème réponse), appelle OBLIGATOIREMENT l'outil \`propose_strategy\` avec une stratégie synthétique. Tu ne dois PAS écrire la stratégie en texte, uniquement via l'outil.

Exemples de bonnes questions :
- "Salut ! Pour commencer, tu fais quoi et tu vends quoi ?"
- "Et tu cherches à toucher qui en priorité ?"
- "C'est pour générer des RDV, ou plutôt te faire connaître ?"
- "Tu veux que mes messages soient chaleureux, directs, ou plutôt pro ?"
- "Combien de personnes tu aimerais contacter par semaine, une idée ?"

Ne dévie jamais du sujet. Si l'utilisateur pose une question hors-sujet, ramène-le gentiment à l'onboarding.`;

export const STRATEGY_TOOL = {
  name: "propose_strategy",
  description:
    "Propose une stratégie d'outbound synthétique à partir des réponses de l'utilisateur. À appeler une seule fois, à la fin de la conversation d'onboarding.",
  input_schema: {
    type: "object",
    properties: {
      identity: {
        type: "string",
        description:
          "Identité courte de l'utilisateur (rôle + entreprise en une phrase).",
      },
      offer: {
        type: "string",
        description: "Ce que vend l'utilisateur, en une phrase.",
      },
      targetSentence: {
        type: "string",
        description:
          "La cible idéale en une phrase naturelle, ex: 'DAF de PME industrielles en France'.",
      },
      targetTitles: {
        type: "array",
        items: { type: "string" },
        description:
          "Titres/rôles de la cible, en français. Ex: ['DAF', 'Directeur financier', 'CFO'].",
      },
      targetIndustries: {
        type: "array",
        items: { type: "string" },
        description:
          "Industries/secteurs ciblés. Ex: ['Industrie', 'Manufacturing'].",
      },
      targetSizes: {
        type: "array",
        items: { type: "string" },
        description:
          "Tailles d'entreprise. Ex: ['50-200 employés', '200-500 employés'].",
      },
      targetLocations: {
        type: "array",
        items: { type: "string" },
        description: "Lieux/pays ciblés. Ex: ['France'].",
      },
      signals: {
        type: "array",
        items: {
          type: "string",
          enum: [
            "posted-recent",
            "job-change",
            "follows-competitor",
            "engaged-content",
            "new-funding",
          ],
        },
        description:
          "Signaux d'intérêt à activer parmi la liste fixe de 5 signaux disponibles.",
      },
      tone: {
        type: "string",
        enum: ["chaleureux", "direct", "formel"],
        description: "Ton général des messages.",
      },
      neverDo: {
        type: "string",
        description:
          "Ce que l'IA ne doit jamais faire, en langage naturel et court. Ex: 'Ne pas pitcher au premier message, rester sympa et humain'.",
      },
      exampleMessage: {
        type: "string",
        description:
          "Un exemple de premier message LinkedIn qui respecte le ton et les contraintes, en français, 3-4 lignes max, adressé à 'Marie' (prospect fictif pour preview).",
      },
      weeklyVolume: {
        type: "number",
        description: "Nombre de contacts par semaine souhaité.",
      },
    },
    required: [
      "identity",
      "offer",
      "targetSentence",
      "targetTitles",
      "targetIndustries",
      "targetLocations",
      "signals",
      "tone",
      "exampleMessage",
    ],
  },
};

export type ProposedStrategy = {
  identity: string;
  offer: string;
  targetSentence: string;
  targetTitles: string[];
  targetIndustries: string[];
  targetSizes?: string[];
  targetLocations: string[];
  signals: string[];
  tone: "chaleureux" | "direct" | "formel";
  neverDo?: string;
  exampleMessage: string;
  weeklyVolume?: number;
};
