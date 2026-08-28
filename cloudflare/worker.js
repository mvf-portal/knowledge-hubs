/**
 * Der Wecker der Knowledge-Hubs.
 *
 * Einmal am Morgen ein einziger Aufruf an GitHub. Er loest im Repo
 * knowledge-hubs den Workflow "Dirigent" aus, und der stoesst die zwoelf
 * Portale an.
 *
 * Warum ueberhaupt: GitHubs eigener Cron ist ausdruecklich "best effort". Am
 * 27. und 28.08.2026 hat er zwei Naechte hintereinander gar nichts gestartet -
 * kein fehlgeschlagener Lauf, sondern gar keiner -, obwohl alle Workflows
 * aktiv waren und jeder Start von Hand sofort lief. Die AUSFUEHRUNG bei GitHub
 * ist verlaesslich, die AUSLOESUNG nicht. Ein Weckruf von aussen behebt genau
 * das - und anders als die Aufgabenplanung auf dem Redaktionsrechner laeuft er
 * auch, wenn dieser Rechner aus ist.
 *
 * Der Schluessel: ein fein granuliertes GitHub-Token mit "Contents: write"
 * NUR auf mvf-portal/knowledge-hubs. Mehr braucht repository_dispatch nicht.
 * Das Token, das die zwoelf Portale anstoesst, liegt in den Secrets von
 * knowledge-hubs und verlaesst GitHub nie.
 *
 * Einrichten: siehe LIESMICH.md in diesem Ordner.
 */

const REPO = "mvf-portal/knowledge-hubs";
const EREIGNIS = "morgenlauf";

async function wecken(env) {
  const antwort = await fetch(`https://api.github.com/repos/${REPO}/dispatches`, {
    method: "POST",
    headers: {
      // GitHub lehnt Anfragen ohne User-Agent mit 403 ab.
      "User-Agent": "mvf-knowledge-hubs-wecker",
      "Accept": "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "Authorization": `Bearer ${env.GITHUB_TOKEN}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      event_type: EREIGNIS,
      client_payload: { quelle: "cloudflare-cron", zeit: new Date().toISOString() },
    }),
  });

  // 204 ist der Erfolgsfall von repository_dispatch - kein Rumpf, kein Inhalt.
  const text = antwort.status === 204 ? "" : await antwort.text();
  const zeile = `${new Date().toISOString()} -> ${antwort.status} ${text}`.trim();
  console.log(zeile);
  return { ok: antwort.status === 204, status: antwort.status, text };
}

export default {
  // Der Zeitplan steht in wrangler.toml. Cloudflare fuehrt ihn auch dann aus,
  // wenn niemand die Seite aufruft - anders als WP-Cron.
  async scheduled(event, env, ctx) {
    ctx.waitUntil(wecken(env));
  },

  /**
   * Aufruf von Hand, zum Prüfen: Die Adresse des Workers mit ?probe=<GEHEIMNIS>
   * aufrufen. Ohne das Geheimnis antwortet der Worker nichts Verwertbares -
   * sonst koennte jeder, der die Adresse kennt, dreizehn Laeufe ausloesen.
   */
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.searchParams.get("probe") !== env.PROBE_GEHEIMNIS) {
      return new Response("Nichts zu sehen.\n", { status: 404 });
    }
    const e = await wecken(env);
    return new Response(
      e.ok ? "Weckruf abgesetzt.\n" : `GitHub antwortete ${e.status}: ${e.text}\n`,
      { status: e.ok ? 200 : 502 });
  },
};
