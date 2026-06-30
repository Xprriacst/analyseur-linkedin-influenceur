import Anthropic from "@anthropic-ai/sdk";

export const runtime = "nodejs";

type WireMessage = { role: "me" | "them"; content: string };

type Body = {
  tone: "chaleureux" | "direct" | "formel";
  neverDo?: string;
  senderOffer?: string;
  leadFirstName: string;
  leadRole: string;
  leadCompany: string;
  history: WireMessage[];
  learnedRules?: string[];
  learnedExamples?: { original: string; edited: string }[];
};

const TONE_GUIDANCE: Record<Body["tone"], string> = {
  chaleureux:
    "Ton chaleureux et humain, tutoiement. Reste naturel et direct.",
  direct: "Ton direct, concis, sans fioritures. Va au but mais poliment.",
  formel:
    "Ton professionnel, vouvoiement. Pas trop corporate, rester humain.",
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

  const rulesBlock =
    body.learnedRules && body.learnedRules.length > 0
      ? `\n\nRègles apprises de l'utilisateur (à respecter) :\n${body.learnedRules
          .map((r) => `- ${r}`)
          .join("\n")}`
      : "";

  const examplesBlock =
    body.learnedExamples && body.learnedExamples.length > 0
      ? `\n\nVoici comment l'utilisateur édite habituellement les messages IA (imite son style) :\n${body.learnedExamples
          .slice(-3)
          .map(
            (e, i) =>
              `Exemple ${i + 1}:\n- Proposé par l'IA: "${e.original}"\n- Réécrit par lui: "${e.edited}"`
          )
          .join("\n\n")}`
      : "";

  const system = `Tu es un assistant qui rédige une RÉPONSE à un message LinkedIn, en français, en imitant le style de l'utilisateur (Alexandre).
${TONE_GUIDANCE[body.tone]}

Contraintes :
- Maximum 3-4 lignes, jamais de formules corporate ("je me permets", "dans le cadre de").
- Tu réponds au DERNIER message du prospect. Tiens compte de tout l'historique.
- Si le prospect pose une question, réponds-y concrètement. Si c'est une ouverture, rebondis naturellement et propose une suite (call, échange, partage d'info).
- Pas de guillemets autour de ta réponse.
${body.neverDo ? `\nCe que l'utilisateur ne veut JAMAIS : ${body.neverDo}` : ""}${rulesBlock}${examplesBlock}

Offre de l'utilisateur (contexte) : ${body.senderOffer ?? "solution B2B d'outbound LinkedIn pilotée par l'IA"}.

Renvoie UNIQUEMENT la réponse, sans préambule.`;

  // On traduit l'historique au format Anthropic : me -> assistant, them -> user.
  // Ici on considère "them" comme user (on génère la prochaine "assistant" = ce qu'on veut envoyer).
  const messages = body.history.map((m) => ({
    role: m.role === "them" ? ("user" as const) : ("assistant" as const),
    content: m.content,
  }));

  // S'assure que le dernier message est bien du prospect (user)
  if (messages.length === 0 || messages[messages.length - 1].role !== "user") {
    messages.push({
      role: "user",
      content: `(Le prospect ${body.leadFirstName} attend une réponse.)`,
    });
  }

  try {
    const resp = await client.messages.create({
      model: "claude-sonnet-4-5",
      max_tokens: 400,
      system,
      messages,
    });
    const text = resp.content
      .filter((c) => c.type === "text")
      .map((c) => (c.type === "text" ? c.text : ""))
      .join("\n")
      .trim();
    return Response.json({ message: text });
  } catch (e) {
    const msg = e instanceof Error ? e.message : "Erreur inconnue";
    console.error("reply-draft error", e);
    return Response.json({ error: msg }, { status: 500 });
  }
}
