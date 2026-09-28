import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type Anthropic from "@anthropic-ai/sdk";
import { resolveVenue, VenueNotMatchedError } from "../lib/venue";
import {
  IdentifiedRestaurant,
  VenueCandidate,
  nameScore,
  pickBestCandidate,
} from "../lib/venueMatch";

const LEI: IdentifiedRestaurant = {
  found: true,
  name: "Lei",
  resy_search_query: "Lei",
  street_address: "15-17 Doyers St",
  city: "New York",
  state_or_region: "NY",
  postal_code: "10013",
  country: "US",
  notes: "",
};

const LEI_RESY: VenueCandidate = {
  id: 89991,
  name: "Lei",
  neighborhood: "Chinatown",
  street_address: "15-17 Doyers St",
  locality: "New York",
  region: "NY",
  postal_code: "10013",
};

// What "lei winebar chinatown nyc" used to resolve to.
const ZARAGOZA: VenueCandidate = {
  id: 76591,
  name: "AMONTILLADO Winebar",
  neighborhood: "Zaragoza",
  street_address: "Calle de Espoz y Mina 21",
  locality: "Zaragoza",
  region: "Aragón",
  postal_code: "50003",
};

describe("nameScore", () => {
  it("ignores filler words like wine bar / nyc", () => {
    expect(nameScore("Lei Wine Bar NYC", "Lei")).toBe(1);
    expect(nameScore("The Coop at Double Chicken Please", "Double Chicken Please")).toBe(1);
  });

  it("scores unrelated names at 0", () => {
    expect(nameScore("Lei", "AMONTILLADO Winebar")).toBe(0);
  });
});

describe("pickBestCandidate", () => {
  it("picks the right venue and rejects the Zaragoza winebar", () => {
    const { best } = pickBestCandidate(LEI, [ZARAGOZA, LEI_RESY]);
    expect(best?.candidate.id).toBe(89991);
  });

  it("returns nothing rather than a wrong venue", () => {
    expect(pickBestCandidate(LEI, [ZARAGOZA]).best).toBeNull();
  });

  it("rejects a same-name venue in another state", () => {
    const elsewhere = { ...LEI_RESY, id: 1, region: "CA", postal_code: "94110", street_address: "1 Main St" };
    expect(pickBestCandidate(LEI, [elsewhere]).best).toBeNull();
  });

  it("rejects a same-name venue at a different address in the same state", () => {
    const other = { ...LEI_RESY, id: 2, street_address: "400 Atlantic Ave", postal_code: "11217" };
    expect(pickBestCandidate(LEI, [other]).best).toBeNull();
  });

  it("accepts a name match when Resy has no address to contradict it", () => {
    const bare = { ...LEI_RESY, street_address: null, locality: null, region: null, postal_code: null };
    expect(pickBestCandidate(LEI, [bare]).best?.candidate.id).toBe(89991);
  });

  it("prefers the candidate whose address matches", () => {
    const noAddr = { ...LEI_RESY, id: 3, street_address: null, postal_code: null };
    expect(pickBestCandidate(LEI, [noAddr, LEI_RESY]).best?.candidate.id).toBe(89991);
  });
});

describe("resolveVenue", () => {
  const searched: string[] = [];

  function fakeClient(...responses: unknown[]) {
    const create = vi.fn();
    for (const r of responses) create.mockResolvedValueOnce(r);
    return { client: { messages: { create } } as unknown as Anthropic, create };
  }
  const identify = (input: IdentifiedRestaurant) => ({
    stop_reason: "tool_use",
    content: [{ type: "tool_use", name: "identify_restaurant", input }],
  });

  function stubResy(results: Record<string, VenueCandidate[]>) {
    const byId = new Map(Object.values(results).flat().map((c) => [c.id, c]));
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url.endsWith("/3/venuesearch/search")) {
          const { query } = JSON.parse(String(init?.body));
          searched.push(query);
          const hits = (results[query] ?? []).map((c) => ({ id: { resy: c.id }, name: c.name }));
          return new Response(JSON.stringify({ search: { hits } }));
        }
        const id = Number(new URL(url).searchParams.get("id"));
        const c = byId.get(id)!;
        return new Response(
          JSON.stringify({
            name: c.name,
            location: {
              address_1: c.street_address,
              locality: c.locality,
              region: c.region,
              postal_code: c.postal_code,
              neighborhood: c.neighborhood,
            },
          })
        );
      })
    );
  }

  beforeEach(() => {
    searched.length = 0;
    vi.stubEnv("RESY_AUTH_TOKEN", "t");
    vi.stubEnv("RESY_API_KEY", "k");
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("searches Resy with the cleaned name, never the raw input", async () => {
    stubResy({ Lei: [LEI_RESY] });
    const { client, create } = fakeClient(identify(LEI));

    const { venue } = await resolveVenue("lei winebar chinatown nyc", client);

    expect(venue).toEqual({
      id: 89991,
      name: "Lei",
      neighborhood: "Chinatown",
      address: "15-17 Doyers St, New York, NY 10013",
    });
    expect(searched).toEqual(["Lei"]);
    const request = create.mock.calls[0][0];
    expect(request.tools.map((t: { name: string }) => t.name)).toEqual(["web_search", "identify_restaurant"]);
    expect(request.messages[0].content).toBe("lei winebar chinatown nyc");
  });

  it("refuses to resolve when Resy only has a different restaurant", async () => {
    stubResy({ Lei: [ZARAGOZA] });
    const { client } = fakeClient(identify(LEI));
    await expect(resolveVenue("lei winebar chinatown nyc", client)).rejects.toThrow(VenueNotMatchedError);
    await expect(
      resolveVenue("lei", fakeClient(identify(LEI)).client)
    ).rejects.toThrow(/AMONTILLADO Winebar \(Calle de Espoz y Mina 21/);
  });

  it("refuses when the restaurant can't be identified, without searching Resy", async () => {
    stubResy({});
    const { client } = fakeClient(identify({ ...LEI, found: false, notes: "No such place." }));
    await expect(resolveVenue("asdf", client)).rejects.toThrow(/No such place/);
    expect(searched).toEqual([]);
  });

  it("resumes a paused turn, then forces the report if needed", async () => {
    stubResy({ Lei: [LEI_RESY] });
    const paused = { stop_reason: "pause_turn", content: [{ type: "text", text: "searching" }] };
    const done = { stop_reason: "end_turn", content: [{ type: "text", text: "It's Lei." }] };
    const { client, create } = fakeClient(paused, done, identify(LEI));

    await expect(resolveVenue("lei", client)).resolves.toMatchObject({ venue: { id: 89991 } });
    expect(create).toHaveBeenCalledTimes(3);
    expect(create.mock.calls[1][0].messages.at(-1)).toEqual({ role: "assistant", content: paused.content });
    expect(create.mock.calls[2][0].tool_choice).toEqual({ type: "tool", name: "identify_restaurant" });
  });
});
