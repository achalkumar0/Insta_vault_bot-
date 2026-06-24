/**
 * Cloudflare Worker for InstaVault Leaderboard Sync
 * Runs every 10 minutes via Cron Trigger to fetch the top 10 users 
 * by lifetime sparks from Firestore and caches them into Upstash Redis.
 */

export default {
  // Triggered by the Cron Schedule
  async scheduled(event, env, ctx) {
    // We catch errors here so the worker doesn't completely crash silently,
    // but the Cron run will log it.
    ctx.waitUntil(
      syncLeaderboard(env).catch(e => console.error("Scheduled Sync Failed:", e.message))
    );
  },
  
  // Optional HTTP trigger for manual syncing / testing via browser
  async fetch(request, env, ctx) {
    // Pro-Tip: Add a simple security check so random internet scanners 
    // don't DDoS your Firebase/Redis by hitting this URL repeatedly.
    const url = new URL(request.url);
    if (url.searchParams.get("secret") !== (env.SYNC_SECRET || "dev-secret-123")) {
      return new Response("Unauthorized", { status: 401 });
    }

    try {
      await syncLeaderboard(env);
      return new Response("Leaderboard (Lifetime) synced successfully", { 
        status: 200,
        headers: { "Cache-Control": "no-store" } // Prevent browser caching
      });
    } catch (error) {
      console.error("Manual Sync Error:", error.stack);
      return new Response(`Sync Failed: ${error.message}`, { status: 500 });
    }
  }
};

// Helper function to add timeout protection to fetch requests
async function fetchWithTimeout(resource, options = {}) {
  const { timeout = 8000 } = options;
  
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeout);
  
  try {
    const response = await fetch(resource, {
      ...options,
      signal: controller.signal  
    });
    return response;
  } finally {
    clearTimeout(id);
  }
}

async function syncLeaderboard(env) {
  const { 
    FIRESTORE_PROJECT_ID, 
    FIRESTORE_API_KEY, 
    UPSTASH_REDIS_REST_URL, 
    UPSTASH_REDIS_REST_TOKEN 
  } = env;

  if (!FIRESTORE_PROJECT_ID || !UPSTASH_REDIS_REST_URL || !FIRESTORE_API_KEY || !UPSTASH_REDIS_REST_TOKEN) {
    throw new Error("Missing required environment variables.");
  }

  // -------------------------------------------------------------
  // 1. Fetch Top 10 Lifetime Users from Firestore (REST API)
  // -------------------------------------------------------------
  const firestoreUrl = `https://firestore.googleapis.com/v1/projects/${FIRESTORE_PROJECT_ID}/databases/(default)/documents:runQuery?key=${FIRESTORE_API_KEY}`;
  
  const queryPayload = {
    structuredQuery: {
      from: [{ collectionId: "users" }],
      orderBy: [{
        field: { fieldPath: "lifetime_sparks" },
        direction: "DESCENDING"
      }],
      limit: 10
    }
  };

  const firestoreResponse = await fetchWithTimeout(firestoreUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(queryPayload),
    timeout: 10000 // 10 seconds timeout for Firestore
  });

  if (!firestoreResponse.ok) {
    throw new Error(`Firestore query failed (${firestoreResponse.status}): ${await firestoreResponse.text()}`);
  }

  const firestoreData = await firestoreResponse.json();
  
  // VALIDATION FIX: Ensure firestoreData is an array
  if (!Array.isArray(firestoreData)) {
      throw new Error(`Invalid response from Firestore: Expected an array, got ${typeof firestoreData}`);
  }

  // Parse Firestore documents
  const topUsers = firestoreData.map(result => {
    const doc = result.document;
    if (!doc) return null; // Firestore returns { readTime: ... } for empty/meta results
    
    const fields = doc.fields || {};
    return {
      _uid: doc.name.split("/").pop(),
      first_name: fields.first_name?.stringValue || "Anonymous",
      lifetime_sparks: parseInt(fields.lifetime_sparks?.integerValue || fields.lifetime_sparks?.doubleValue || 0, 10)
    };
  }).filter(Boolean); // Clean up nulls

  // -------------------------------------------------------------
  // 2. Save Data to Redis via Upstash REST API
  // -------------------------------------------------------------
  // UPSTASH FIX: Use URL parameters for EX (Expiry) and send value directly in body
  const redisUrl = `${UPSTASH_REDIS_REST_URL}/set/leaderboard:lifetime?EX=900`;
  
  const redisResponse = await fetchWithTimeout(redisUrl, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${UPSTASH_REDIS_REST_TOKEN}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify(topUsers),
    timeout: 5000 // 5 seconds timeout for Redis
  });

  if (!redisResponse.ok) {
    throw new Error(`Redis sync failed (${redisResponse.status}): ${await redisResponse.text()}`);
  }

  console.log(`Successfully synced ${topUsers.length} users to Redis leaderboard:lifetime`);
  return true; // Indicate success to caller
}
