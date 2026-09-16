// Reads/writes resy-sniper/targets.json in the fun-scripts repo via the
// GitHub Contents API. Committing to master is what actually changes what
// the deployed bot watches - a GitHub Actions workflow (resy-sniper-deploy.yml)
// redeploys the Fly.io app on every push touching resy-sniper/**, since
// targets.json is baked into the bot's Docker image rather than fetched
// at runtime.

const OWNER = "edisonmoy";
const REPO = "fun-scripts";
const PATH = "resy-sniper/targets.json";
const BRANCH = "master";

export interface Booking {
  day: string; // "YYYY-MM-DD"
  time: string; // "HH:MM", 24h
  reservation_id: string;
}

export interface Target {
  key: string;
  venue_name: string;
  request: string;
  venue_id?: number | null;
  party_size_override?: number | null;
  enabled?: boolean;
  dry_run?: boolean | null;
  // Set by the bot (github_sync.py) once this target books - the webapp
  // never writes this itself, only displays/preserves it.
  booking?: Booking | null;
}

function githubHeaders() {
  const token = process.env.GITHUB_TOKEN;
  if (!token) throw new Error("GITHUB_TOKEN is not set");
  return {
    Authorization: `Bearer ${token}`,
    Accept: "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
  };
}

export async function fetchTargets(): Promise<{ targets: Target[]; sha: string }> {
  const url = `https://api.github.com/repos/${OWNER}/${REPO}/contents/${PATH}?ref=${BRANCH}`;
  const resp = await fetch(url, { headers: githubHeaders(), cache: "no-store" });
  if (!resp.ok) {
    throw new Error(`GitHub fetch failed (${resp.status}): ${await resp.text()}`);
  }
  const data = await resp.json();
  const content = Buffer.from(data.content, "base64").toString("utf-8");
  return { targets: JSON.parse(content), sha: data.sha };
}

export async function saveTargets(targets: Target[], sha: string, message: string): Promise<void> {
  const url = `https://api.github.com/repos/${OWNER}/${REPO}/contents/${PATH}`;
  const body = JSON.stringify(targets, null, 2) + "\n";
  const content = Buffer.from(body, "utf-8").toString("base64");
  const resp = await fetch(url, {
    method: "PUT",
    headers: { ...githubHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify({ message, content, sha, branch: BRANCH }),
  });
  if (!resp.ok) {
    throw new Error(`GitHub save failed (${resp.status}): ${await resp.text()}`);
  }
}
