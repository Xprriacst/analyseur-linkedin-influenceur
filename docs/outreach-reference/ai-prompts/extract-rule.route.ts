import Anthropic from "@anthropic-ai/sdk";
import type { Tool } from "@anthropic-ai/sdk/resources/messages";

export const runtime = "nodejs";

const TOOL = {
  name: "extract_style_rule",
  description:
    "Extrait une règle de style actionnable à partir de la différence entre un message proposé par l'IA et sa version éditée par l'utilisateur. Si aucune règle claire n'émerge, retourne rule: null.",
  input_schema: {
    type: "object",
    properties: {
      rule: {
        type: "string",
        description:
          "Règle de style courte (1 phrase) en français, à la forme impérative. Ex: 'Ne jamais commencer par Bonjour, préférer Hello'. null si aucune règle claire.",
      },
    },
    required: ["rule"],
  },
};

export async function POST(req: Request) {
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    return Response.json({ rule: null }, { status: 200 });
  }
  const { original, edited } = (await req.json()) as {
    original: string;
    edited: string;
  };
  if (!original || !edited || original.trim() === edited.trim()) {
    return Response.json({ rule: null });
  }

  const client = new Anthropic({ apiKey });

  try {
    const resp = await client.messages.create({
      model: "claude-sonnet-4-5",
      max_tokens: 200,
      system:
        "Tu analyses comment un utilisateur réécrit les messages proposés par l'IA, pour en extraire UNE règle de style courte et généralisable (pas spécifique au contexte du message). Appelle toujours l'outil extract_style_rule. Si le changement est trop mineur ou trop spécifique, renvoie rule: null.",
      tools: [TOOL as Tool],
      tool_choice: { type: "tool", name: "extract_style_rule" },
      messages: [
        {
          role: "user",
          content: `Proposé par l'IA:\n"${original}"\n\nRéécrit par l'utilisateur:\n"${edited}"\n\nQuelle règle de style en tirer ?`,
        },
      ],
    });

    const toolUse = resp.content.find((c) => c.type === "tool_use");
    if (!toolUse || toolUse.type !== "tool_use") {
      return Response.json({ rule: null });
    }
    const input = toolUse.input as { rule: string | null };
    return Response.json({ rule: input.rule });
  } catch (e) {
    console.error("extract-rule error", e);
    return Response.json({ rule: null });
  }
}
