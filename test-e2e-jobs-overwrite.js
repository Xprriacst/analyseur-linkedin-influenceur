/**
 * E2E prod — job queue multi-profils + écrasement analyse (ALE-53).
 *
 * Prérequis : TEST_EMAIL + TEST_PASSWORD (compte de test Supabase).
 *
 *   TEST_EMAIL=test@... TEST_PASSWORD=... node test-e2e-jobs-overwrite.js
 */

const SUPABASE_URL = process.env.SUPABASE_URL || "https://zcxaxwqkswuefzlzpgvi.supabase.co";
const SUPABASE_ANON =
  process.env.SUPABASE_ANON_KEY ||
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ||
  "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InpjeGF4d3Frc3d1ZWZ6bHpwZ3ZpIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODEwMjU2NjIsImV4cCI6MjA5NjYwMTY2Mn0.AO5J-JdO0XYSvaRejq44cvnX1pC6qactw7X9O9-mS9U";
const BACKEND =
  process.env.BACKEND_URL ||
  process.env.NEXT_PUBLIC_BACKEND_URL ||
  "https://analyseur-linkedin-influenceur-api.onrender.com";
const EMAIL = process.env.TEST_EMAIL;
const PASSWORD = process.env.TEST_PASSWORD;

const PROFILE_A = "https://www.linkedin.com/in/williamhgates/";
const PROFILE_B = "https://www.linkedin.com/in/satyanadella/";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function signIn() {
  const res = await fetch(`${SUPABASE_URL}/auth/v1/token?grant_type=password`, {
    method: "POST",
    headers: { apikey: SUPABASE_ANON, "Content-Type": "application/json" },
    body: JSON.stringify({ email: EMAIL, password: PASSWORD }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(`Auth failed (${res.status}): ${data.error_description || data.msg || JSON.stringify(data)}`);
  return data.access_token;
}

async function api(token, path, opts = {}) {
  const res = await fetch(`${BACKEND}${path}`, {
    ...opts,
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      ...(opts.headers || {}),
    },
  });
  const text = await res.text();
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    data = { raw: text };
  }
  if (!res.ok) {
    const detail = typeof data.detail === "object" ? JSON.stringify(data.detail) : (data.detail || text);
    throw new Error(`${opts.method || "GET"} ${path} → ${res.status}: ${detail}`);
  }
  return data;
}

async function waitJob(token, jobId, timeoutMs = 600000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const job = await api(token, `/jobs/${jobId}`);
    const items = job.items || [];
    const summary = items.map((i) => `${i.handle || "?"}:${i.status}`).join(", ");
    console.log(`   [poll] job=${job.status} ${job.completed}/${job.total} — ${summary}`);
    if (job.status === "done" || job.status === "error" || job.status === "cancelled") return job;
    await sleep(5000);
  }
  throw new Error(`Timeout après ${timeoutMs / 1000}s (job ${jobId})`);
}

(async () => {
  if (!EMAIL || !PASSWORD) {
    console.error("❌ TEST_EMAIL et TEST_PASSWORD requis.");
    process.exit(2);
  }

  console.log(`🔑 Compte : ${EMAIL}`);
  console.log(`🌐 Backend : ${BACKEND}`);

  const token = await signIn();
  console.log("✅ Auth OK");

  const reportsBefore = await api(token, "/reports");
  console.log(`📊 Rapports avant : ${reportsBefore.length}`);

  console.log("\n1️⃣  Série multi-profils (2 URLs, sans LLM, cache on)…");
  const job1 = await api(token, "/jobs", {
    method: "POST",
    body: JSON.stringify({
      profile_urls: [PROFILE_A, PROFILE_B],
      limit: 10,
      run_llm: false,
      use_cache: true,
    }),
  });
  console.log(`   Job créé : ${job1.id}`);

  const done1 = await waitJob(token, job1.id);
  const itemA1 = (done1.items || []).find((i) => i.url.includes("williamhgates"));
  const itemB = (done1.items || []).find((i) => i.url.includes("satyanadella"));

  if (done1.status !== "done") throw new Error(`Série 1 échouée : status=${done1.status}`);
  if (!itemA1?.analysis_id || itemA1.status !== "done") throw new Error(`Profil A non terminé : ${JSON.stringify(itemA1)}`);
  if (!itemB?.analysis_id || itemB.status !== "done") throw new Error(`Profil B non terminé : ${JSON.stringify(itemB)}`);

  console.log(`   ✅ Série 1 OK — gates analysis_id=${itemA1.analysis_id}, nadella analysis_id=${itemB.analysis_id}`);

  const reportsMid = await api(token, "/reports");
  console.log(`📊 Rapports après série 1 : ${reportsMid.length}`);

  console.log("\n2️⃣  Relance du même profil (williamhgates)…");
  const analysisIdBefore = itemA1.analysis_id;
  await sleep(2000);

  const job2 = await api(token, "/jobs", {
    method: "POST",
    body: JSON.stringify({
      profile_urls: [PROFILE_A],
      limit: 10,
      run_llm: false,
      use_cache: true,
    }),
  });
  console.log(`   Job créé : ${job2.id}`);

  const done2 = await waitJob(token, job2.id);
  const itemA2 = (done2.items || [])[0];

  if (done2.status !== "done" || itemA2?.status !== "done") {
    throw new Error(`Relance échouée : ${JSON.stringify(done2)}`);
  }

  console.log(`   analysis_id avant=${analysisIdBefore} après=${itemA2.analysis_id}`);

  const reportsAfter = await api(token, "/reports");
  console.log(`📊 Rapports après relance : ${reportsAfter.length}`);

  const gatesReports = reportsAfter.filter((r) => (r.handle || "").includes("williamhgates") || (r.name || "").toLowerCase().includes("gates"));
  const dupGateRows = gatesReports.length;

  let pass = true;
  if (itemA2.analysis_id !== analysisIdBefore) {
    console.log("⚠️  analysis_id a changé (upsert peut réutiliser la même row — vérifier count rapports)");
  }
  if (reportsAfter.length > reportsMid.length) {
    console.log(`❌ FAIL — accumulation rapports : ${reportsMid.length} → ${reportsAfter.length}`);
    pass = false;
  } else if (reportsAfter.length === reportsMid.length) {
    console.log("✅ PASS — nombre de rapports inchangé après relance (écrasement, pas accumulation)");
  }

  if (dupGateRows > 1) {
    console.log(`❌ FAIL — ${dupGateRows} entrées williamhgates dans /reports`);
    pass = false;
  } else {
    console.log(`✅ PASS — une seule entrée williamhgates dans /reports`);
  }

  if (pass) {
    console.log("\n✅ E2E PASS — job queue multi-profils + écrasement OK");
    process.exit(0);
  }
  console.log("\n❌ E2E FAIL");
  process.exit(1);
})().catch((err) => {
  console.error(`\n❌ ${err.message}`);
  process.exit(1);
});
