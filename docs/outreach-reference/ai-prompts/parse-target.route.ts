import Anthropic from "@anthropic-ai/sdk";
import type { Tool } from "@anthropic-ai/sdk/resources/messages";

export const runtime = "nodejs";

const TOOL = {
  name: "extract_target_chips",
  description:
    "Extrait les chips de cible (titres, industries, tailles, lieux) à partir d'une description libre en français.",
  input_schema: {
    type: "object",
    properties: {
      titles: {
        type: "array",
        items: { type: "string" },
        description:
          "Titres de poste en français, 1 à 5 éléments. Ex: ['DAF', 'Directeur financier'].",
      },
      industries: {
        type: "array",
        items: { type: "string" },
        description: "Industries/secteurs. Ex: ['Industrie', 'Manufacturing'].",
      },
      sizes: {
        type: "array",
        items: { type: "string" },
        description:
          "Tailles d'entreprise. Utilise ces formats: '1-10 employés', '11-50 employés', '50-200 employés', '200-500 employés', '500-1000 employés', '1000+ employés'.",
      },
      locations: {
        type: "array",
        items: { type: "string" },
        description: "Lieux/pays. Ex: ['France', 'Belgique'].",
      },
    },
    required: ["titles", "industries", "locations"],
  },
};

export async function POST(req: Request) {
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    return Response.json(
      { error: "ANTHROPIC_API_KEY manquante" },
      { status: 500 }
    );
  }
  const { sentence } = (await req.json()) as { sentence: string };
  if (!sentence?.trim()) {
    return Response.json({ error: "Phrase vide" }, { status: 400 });
  }

  const client = new Anthropic({ apiKey });

  try {
    const resp = await client.messages.create({
      model: "claude-sonnet-4-5",
      max_tokens: 512,
      system:
        "Tu es un extracteur de critères B2B. À partir d'une description libre de cible idéale en français, appelle OBLIGATOIREMENT l'outil extract_target_chips. Si un critère n'est pas explicite, déduis intelligemment (ex: 'PME' → tailles 11-50 et 50-200 ; 'industriel' → industrie 'Industrie'). Ne réponds JAMAIS en texte, uniquement via l'outil.",
      tools: [TOOL as Tool],
      tool_choice: { type: "tool", name: "extract_target_chips" },
      messages: [{ role: "user", content: sentence }],
    });

    const toolUse = resp.content.find((c) => c.type === "tool_use");
    if (!toolUse || toolUse.type !== "tool_use") {
      return Response.json({ error: "Pas de tool_use" }, { status: 500 });
    }

    return Response.json(toolUse.input);
  } catch (e) {
    const msg = e instanceof Error ? e.message : "Erreur inconnue";
    console.error("parse-target error", e);
    return Response.json({ error: msg }, { status: 500 });
  }
}
