// Turns what the user typed in "Venue name" ("lei winebar chinatown nyc")
// into a specific Resy venue id - without ever passing the raw text to
// Resy's search, which matches words in venue names worldwide and would
// happily return "AMONTILLADO Winebar" in Zaragoza for that input.
//
// 1. Claude, with web search, identifies the actual restaurant: its proper
//    name, a clean Resy search query, and its address.
// 2. Resy is searched with that clean query only.
// 3. Each Resy candidate is checked against the identified name and
//    address (lib/venueMatch.ts). No acceptable match -> an error listing
//    what Resy returned, never a silent first-hit guess.

import Anthropic from "@anthropic-ai/sdk";
import { searchVenues } from "./resy";
import {
  IdentifiedRestaurant,
  VenueCandidate,
  formatCandidateAddress,
  pickBestCandidate,
} from "./venueMatch";

// Web search needs a model that supports web_search_20260209; this runs
// once per Check & Save, so the stronger model's cost doesn't matter.
const MODEL = "claude-sonnet-5";
const TOOL_NAME = "identify_restaurant";
const MAX_TURNS = 3;

const IDENTIFY_TOOL: Anthropic.Tool = {
  name: TOOL_NAME,
  description: "Report which specific real-world restaurant the user means.",
  strict: true,
  input_schema: {
    type: "object",
    properties: {
      found: {
        type: "boolean",
        description: "False if you could not confidently identify one specific restaurant.",
      },
      name: {
        type: "string",
        description: "The restaurant's proper name, as it is listed publicly (e.g. 'Lei').",
      },
      resy_search_query: {
        type: "string",
        description:
          "What to type into Resy's venue search: the restaurant's name only. No city, " +
          "neighborhood, cuisine or other location words - Resy matches words in venue " +
          "names, so extra words make it match the wrong restaurant.",
      },
      street_address: { type: ["string", "null"], description: "e.g. '15-17 Doyers St'" },
      city: { type: ["string", "null"] },
      state_or_region: {
        type: ["string", "null"],
        description: "Two-letter state code for US restaurants, e.g. 'NY'.",
      },
      postal_code: { type: ["string", "null"] },
      country: { type: ["string", "null"] },
      notes: {
        type: "string",
        description: "Anything ambiguous, e.g. several locations or a recent name change.",
      },
    },
    required: [
      "found",
      "name",
      "resy_search_query",
      "street_address",
      "city",
      "state_or_region",
      "postal_code",
      "country",
      "notes",
    ],
    additionalProperties: false,
  },
};

const SYSTEM_PROMPT =
  "Identify the specific restaurant a user means from a loose description they typed " +
  "into a reservation tool - it may include typos, the neighborhood, the city, or what " +
  "kind of place it is. The user is based in New York City: when no location is given, " +
  "assume NYC. Use web search to confirm the restaurant exists and to get its proper " +
  `name and street address, then call ${TOOL_NAME}. If the description could match ` +
  "several places, pick the best match and say so in notes. Set found=false only if " +
  "you cannot identify a specific restaurant.";

function extract(response: Anthropic.Message): IdentifiedRestaurant | null {
  const block = response.content.find(
    (b): b is Anthropic.ToolUseBlock => b.type === "tool_use" && b.name === TOOL_NAME
  );
  return block ? (block.input as IdentifiedRestaurant) : null;
}

export async function identifyRestaurant(
  userInput: string,
  client: Anthropic = new Anthropic()
): Promise<IdentifiedRestaurant> {
  let messages: Anthropic.MessageParam[] = [{ role: "user", content: userInput }];
  let response: Anthropic.Message | null = null;

  for (let turn = 0; turn < MAX_TURNS; turn++) {
    response = await client.messages.create({
      model: MODEL,
      max_tokens: 2048,
      system: SYSTEM_PROMPT,
      tools: [{ type: "web_search_20260209", name: "web_search", max_uses: 2 }, IDENTIFY_TOOL],
      tool_choice: { type: "any" },
      messages,
    });
    const result = extract(response);
    if (result) return result;
    if (response.stop_reason !== "pause_turn") break;
    messages = [...messages, { role: "assistant", content: response.content }];
  }

  // Searched but never reported - force the report with what it found.
  response = await client.messages.create({
    model: MODEL,
    max_tokens: 1024,
    system: SYSTEM_PROMPT,
    tools: [IDENTIFY_TOOL],
    tool_choice: { type: "tool", name: TOOL_NAME },
    messages: [
      ...messages,
      { role: "assistant", content: response!.content },
      { role: "user", content: `Call ${TOOL_NAME} now with your best identification.` },
    ],
  });
  const result = extract(response);
  if (!result) throw new Error("Couldn't identify the restaurant");
  return result;
}

export interface ResolvedVenueResult {
  id: number;
  name: string;
  neighborhood: string | null;
  address: string | null;
}

export class VenueNotMatchedError extends Error {}

function describe(c: VenueCandidate): string {
  const where = formatCandidateAddress(c);
  return where ? `${c.name} (${where})` : c.name;
}

export async function resolveVenue(
  userInput: string,
  client?: Anthropic
): Promise<{ venue: ResolvedVenueResult; identified: IdentifiedRestaurant }> {
  const identified = await identifyRestaurant(userInput, client);
  if (!identified.found || !identified.resy_search_query.trim()) {
    throw new VenueNotMatchedError(
      `Couldn't identify a specific restaurant from "${userInput}".` +
        (identified.notes ? ` ${identified.notes}` : "")
    );
  }

  // Search the clean query, then the bare name if that differs - dedupe by id.
  const queries = [...new Set([identified.resy_search_query.trim(), identified.name.trim()])];
  const seen = new Map<number, VenueCandidate>();
  for (const q of queries) {
    for (const c of await searchVenues(q)) seen.set(c.id, c);
  }
  const candidates = [...seen.values()];

  const { best } = pickBestCandidate(identified, candidates);
  if (!best) {
    const where = [identified.street_address, identified.city, identified.state_or_region]
      .filter(Boolean)
      .join(", ");
    const found = candidates.length
      ? `Resy returned: ${candidates.map(describe).join("; ")}.`
      : "Resy returned no results.";
    throw new VenueNotMatchedError(
      `"${identified.name}"${where ? ` (${where})` : ""} isn't on Resy, or its Resy listing ` +
        `didn't match. ${found}`
    );
  }

  const c = best.candidate;
  return {
    venue: {
      id: c.id,
      name: c.name,
      neighborhood: c.neighborhood,
      address: formatCandidateAddress(c),
    },
    identified,
  };
}
