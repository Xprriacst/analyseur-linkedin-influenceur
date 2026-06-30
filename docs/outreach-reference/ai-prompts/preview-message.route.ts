import Anthropic from "@anthropic-ai/sdk";

export const runtime = "nodejs";

type Body = {
  tone: "chaleureux" | "direct" | "formel";
  neverDo?: string;
  leadFirstName?: string;
  leadRole?: string;
  leadCompany?: string;
  leadSignal?: string; // contexte du signal détecté
  senderOffer?: string; // ce que vend l'utilisateur
  learnedRules?: string[]; // règles apprises du style profile
  learnedExamples?: { original: string; edited: string }[];
};

const TONE_GUIDANCE: Record<Body["tone"], string> = {
  chaleureux:
    "Ton chaleureux et humain. Tutoiement. Commence par quelque chose de personnel lié au contexte du prospect, pas par un pitch.",
  direct:
    "Ton direct, concis, franc. Va droit au but mais sans agressivité. Tutoiement possible selon la cible.",
  formel:
    "Ton professionnel et respectueux. Vouvoiement. Pas trop corporate non plus — rester humain.",
};

export async function POST(req: Request) {
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    return Response.json(
      { error: "ANTHROPIC_API_KEY manquante" },
      { status: 500 }
    );
  }

  const body = (await req.json()) as Body;
  const client = new Anthropic({ apiKey });

  const leadFirst = body.leadFirstName ?? "Marie";
  const leadRole = body.leadRole ?? "Directrice marketing";
  const leadCompany = body.leadCompany ?? "Acme Corp";
  const signal =
    body.leadSignal ??
    "vient de poster sur LinkedIn sur la transition digitale industrielle";
  const offer = body.senderOffer ?? "une solution d'outbound LinkedIn pilotée par l'IA";

  const examplesBlock =
    body.learnedExamples && body.learnedExamples.length > 0
      ? `\n\nVoici comment l'utilisateur édite habituellement les messages IA (important, imite son style) :\n${body.learnedExamples
          .slice(-3)
          .map(
            (e, i) =>
              `Exemple ${i + 1}:\n- Proposé par l'IA: "${e.original}"\n- Réécrit par lui: "${e.edited}"`
          )
          .join("\n\n")}`
      : "";

  const rulesBlock =
    body.learnedRules && body.learnedRules.length > 0
      ? `\n\nRègles de style apprises de l'utilisateur (à respecter) :\n${body.learnedRules.map((r) => `- ${r}`).join("\n")}`
      : "";

  const system = `Tu es un rédacteur de messages LinkedIn outbound en français. Tu écris un PREMIER message d'approche.
${TONE_GUIDANCE[body.tone]}

Contraintes strictes :
- Maximum 3-4 lignes, pas de blabla.
- Français naturel, pas de formule corporate ("je me permets", "dans le cadre de").
- Pas d'émoji sauf si le ton l'appelle vraiment.
- Pas de question fermée type "es-tu intéressé ?". Préfère une ouverture naturelle.
- NE PAS pitcher l'offre au premier message sauf si explicitement demandé.
- Le "Contexte" décrit une activité publique du prospect sur LinkedIn (post tiers qu'il a liké/commenté, changement de poste, etc.). Ce n'est PAS du contenu publié par l'utilisateur. Ne jamais écrire "merci d'avoir réagi à mon post" ou suggérer que le prospect a interagi avec l'utilisateur.
${body.neverDo ? `\nCe que l'utilisateur ne veut JAMAIS : ${body.neverDo}` : ""}${rulesBlock}${examplesBlock}

Renvoie UNIQUEMENT le message, sans guillemets ni préambule.`;

  const user = `Écris un premier message à ${leadFirst}, ${leadRole} chez ${leadCompany}. Contexte : ${signal}. Mon offre : ${offer}.`;

  try {
    const resp = await client.messages.create({
      model: "claude-sonnet-4-5",
      max_tokens: 400,
      system,
      messages: [{ role: "user", content: user }],
    });
    const text = resp.content
      .filter((c) => c.type === "text")
      .map((c) => (c.type === "text" ? c.text : ""))
      .join("\n")
      .trim();
    return Response.json({ message: text });
  } catch (e) {
    const msg = e instanceof Error ? e.message : "Erreur inconnue";
    console.error("preview-message error", e);
    return Response.json({ error: msg }, { status: 500 });
  }
}
