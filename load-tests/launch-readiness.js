// k6 launch-readiness — carga realista contra PRODUÇÃO (#1631).
//
// ⚠️ Este script fala com produção. Leia docs/runbooks/k6-launch-readiness.md
// antes de rodar. Resumo do que importa:
//   - janela 22h30–23h30 BRT (fora de pico);
//   - alvo é t2.micro, 1 vCPU / 1 GB, gunicorn 2×2 — quatro requisições em voo;
//   - `checkout_probe` cria assinatura de verdade: no máximo 5, nunca segue o
//     redirect, e as contas são purgadas depois.
//
// Uso:
//   k6 run --summary-export=summary.json \
//     -e BASE_URL=https://api.auraxis.com.br \
//     -e LOADTEST_ACCOUNTS="$(cat accounts.json)" \
//     load-tests/launch-readiness.js
//
// Cenários ligáveis por env (todos default OFF exceto read_baseline):
//   -e READ_SPIKE=true  -e AUTH_PROBE=true  -e CHECKOUT_PROBE=true
//   -e AUTH_BURST=true   ← exige janela com os DOIS limitadores afrouxados
//
// Rodar tudo de uma vez não é o caminho: o veredito de cada cenário depende de
// observar CPUCreditBalance e memória enquanto ele roda, e cenários somados
// tornam impossível dizer qual deles gastou o crédito.

import http from "k6/http";
import { check, sleep, fail } from "k6";
import { Counter, Rate, Trend } from "k6/metrics";

const BASE_URL = __ENV.BASE_URL || "http://localhost:5000";
const ACCOUNTS_RAW = __ENV.LOADTEST_ACCOUNTS || "[]";

const on = (name) => String(__ENV[name] || "").toLowerCase() === "true";

// ── Métricas próprias ────────────────────────────────────────────────────
// 429 não é falha: é a proteção funcionando. Mas 429 do nginx e 429 da
// aplicação significam coisas diferentes, e somá-los esconde qual camada
// segurou a carga. O 429 da app carrega X-RateLimit-Rule; o do nginx não.
const rateLimitedByProxy = new Counter("auraxis_rate_limited_proxy");
const rateLimitedByApp = new Counter("auraxis_rate_limited_app");
const serverErrors = new Counter("auraxis_server_errors_5xx");
const readLatency = new Trend("auraxis_read_latency", true);
const readSuccess = new Rate("auraxis_read_success");

/**
 * Classifica um 429 pela camada que o emitiu.
 *
 * @param {object} res Resposta do k6.
 * @returns {"proxy"|"app"|null} Camada, ou null quando não é 429.
 */
function classifyRateLimit(res) {
  if (res.status !== 429) {
    return null;
  }
  // Cabeçalho posto pelo after_request do middleware da aplicação.
  const rule = res.headers["X-Ratelimit-Rule"] || res.headers["x-ratelimit-rule"];
  return rule ? "app" : "proxy";
}

/**
 * Registra a resposta nas métricas próprias.
 *
 * @param {object} res Resposta do k6.
 * @param {boolean} isRead Se conta para as métricas de leitura.
 */
function record(res, isRead) {
  const limited = classifyRateLimit(res);
  if (limited === "app") {
    rateLimitedByApp.add(1);
  } else if (limited === "proxy") {
    rateLimitedByProxy.add(1);
  }
  if (res.status >= 500) {
    serverErrors.add(1);
  }
  if (isRead) {
    readLatency.add(res.timings.duration);
    readSuccess.add(res.status === 200);
  }
}

// 429 entra como status esperado para não poluir `http_req_failed`, que é o
// gatilho de abort. Sem isto o teste abortaria ao encostar no rate limit — ou
// seja, exatamente quando a proteção funciona.
http.setResponseCallback(http.expectedStatuses(200, 201, 204, 401, 429));

const scenarios = {};

// O runbook manda rodar UM cenário por vez — somados, é impossível dizer qual
// gastou o crédito de CPU. Por isso cada cenário começa em 0s e o piso só entra
// junto quando pedido explicitamente (`-e WITH_BASELINE=true`), como tráfego de
// fundo. Sem isto, `-e CHECKOUT_PROBE=true` deixaria o k6 ocioso por 40 minutos
// esperando um `startTime` que só faz sentido numa execução única.
const selected = ["READ_SPIKE", "AUTH_PROBE", "AUTH_BURST", "CHECKOUT_PROBE"].some(on);

// ── read_baseline — o piso ───────────────────────────────────────────────
// 2 req/s por 5 min. Serve de controle: se a latência já estiver ruim aqui,
// nada medido depois quer dizer alguma coisa.
if (!selected || on("WITH_BASELINE")) {
  scenarios.read_baseline = {
    executor: "constant-arrival-rate",
    rate: 2,
    timeUnit: "1s",
    duration: "5m",
    preAllocatedVUs: 5,
    maxVUs: 20,
    exec: "readWorkload",
    tags: { scenario: "read_baseline" },
  };
}

// ── read_spike — o cenário de divulgação ─────────────────────────────────
// 0→10 req/s em 15 min. ~100 visitantes simultâneos ≈ 8-10 req/s de API.
if (on("READ_SPIKE")) {
  scenarios.read_spike = {
    executor: "ramping-arrival-rate",
    startRate: 1,
    timeUnit: "1s",
    preAllocatedVUs: 10,
    maxVUs: 60,
    stages: [
      { duration: "5m", target: 5 },
      { duration: "5m", target: 10 },
      { duration: "5m", target: 10 },
    ],
    exec: "readWorkload",
    tags: { scenario: "read_spike" },
  };
}

// ── auth_probe — onde o freio pega ───────────────────────────────────────
// 0,3 req/s = 18/min. Acima do nginx (15r/m sustentado, burst 10) e abaixo do
// limitador da app (20/min/IP). O resultado esperado NÃO é 200 em tudo: é
// medir em que ponto o proxy começa a segurar — e confirmar que segura ELE,
// antes do Argon2, que é o objetivo de #1632.
if (on("AUTH_PROBE")) {
  scenarios.auth_probe = {
    executor: "constant-arrival-rate",
    rate: 18,
    timeUnit: "1m",
    duration: "5m",
    preAllocatedVUs: 3,
    maxVUs: 10,
    exec: "authWorkload",
    tags: { scenario: "auth_probe" },
  };
}

// ── auth_burst — só com janela controlada ────────────────────────────────
// 1→3 req/s de login real. Mede o teto do Argon2, e por isso EXIGE os dois
// limitadores afrouxados: o da app (RATE_LIMIT_AUTH_LIMIT) e o do nginx
// (zone=auth_hash). Com qualquer um deles no valor de produção, isto mede o
// limitador e não a CPU. Ver o kill-switch no runbook.
if (on("AUTH_BURST")) {
  scenarios.auth_burst = {
    executor: "ramping-arrival-rate",
    startRate: 1,
    timeUnit: "1s",
    preAllocatedVUs: 5,
    maxVUs: 20,
    stages: [
      { duration: "4m", target: 2 },
      { duration: "6m", target: 3 },
    ],
    exec: "authWorkload",
    tags: { scenario: "auth_burst" },
  };
}

// ── checkout_probe — 5 iterações, nunca mais ─────────────────────────────
// Cria assinatura de verdade no gateway. `maxDuration` e `iterations` são o
// freio; `redirects: 0` garante que paramos ao receber a URL, sem visitar a
// página de pagamento.
if (on("CHECKOUT_PROBE")) {
  scenarios.checkout_probe = {
    executor: "shared-iterations",
    vus: 1,
    iterations: 5,
    maxDuration: "3m",
    exec: "checkoutWorkload",
    tags: { scenario: "checkout_probe" },
  };
}

export const options = {
  scenarios,
  thresholds: {
    // Aborta a execução se a taxa de erro real passar de 1% — 429 e 401 já
    // estão fora da conta pelo responseCallback acima.
    http_req_failed: [{ threshold: "rate<0.01", abortOnFail: true }],
    auraxis_read_latency: ["p(95)<800", "p(99)<2000"],
    auraxis_read_success: ["rate>0.99"],
    auraxis_server_errors_5xx: ["count<1"],
  },
};

/**
 * Faz login nas contas pré-criadas e devolve os tokens.
 *
 * As contas são criadas fora daqui (ver runbook): registrar em massa dentro do
 * teste gastaria o orçamento de Argon2 que estamos justamente medindo, e
 * deixaria lixo em produção a cada execução.
 *
 * @returns {{tokens: string[]}} Tokens de acesso utilizáveis pelos cenários.
 */
export function setup() {
  const accounts = JSON.parse(ACCOUNTS_RAW);
  if (!Array.isArray(accounts) || accounts.length === 0) {
    fail(
      "LOADTEST_ACCOUNTS vazio. Crie as contas qa-loadtest-* conforme o runbook " +
        "e passe o JSON [{email,password}] — sem elas os cenários de leitura " +
        "mediriam apenas 401.",
    );
  }

  const tokens = [];
  for (const account of accounts) {
    const res = http.post(
      `${BASE_URL}/auth/login`,
      JSON.stringify({ email: account.email, password: account.password }),
      { headers: { "Content-Type": "application/json", "X-API-Contract": "v2" } },
    );
    const body = res.json();
    const token = body && body.data ? body.data.token || body.data.access_token : null;
    if (token) {
      tokens.push(token);
    } else {
      console.warn(`login falhou para ${account.email}: HTTP ${res.status}`);
    }
  }

  if (tokens.length === 0) {
    fail("nenhuma conta de carga autenticou — abortando antes de gerar tráfego");
  }
  console.log(`setup: ${tokens.length}/${accounts.length} contas autenticadas`);
  return { tokens };
}

/**
 * Cabeçalhos autenticados de uma das contas de carga.
 *
 * @param {{tokens: string[]}} data Retorno do setup.
 * @returns {object} Cabeçalhos HTTP.
 */
function authHeaders(data) {
  const token = data.tokens[__VU % data.tokens.length];
  return {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
    "X-API-Contract": "v2",
  };
}

/**
 * Sessão de leitura típica: o que um usuário abre ao entrar.
 *
 * @param {{tokens: string[]}} data Retorno do setup.
 */
export function readWorkload(data) {
  const headers = authHeaders(data);
  const month = new Date().toISOString().slice(0, 7);

  const health = http.get(`${BASE_URL}/healthz`, { tags: { name: "GET /healthz" } });
  check(health, { "healthz 200": (r) => r.status === 200 });
  record(health, false);

  const overview = http.get(`${BASE_URL}/dashboard/overview?month=${month}`, {
    headers,
    tags: { name: "GET /dashboard/overview" },
  });
  record(overview, true);

  const transactions = http.get(`${BASE_URL}/transactions?page=1&per_page=20`, {
    headers,
    tags: { name: "GET /transactions" },
  });
  record(transactions, true);

  const bootstrap = http.get(`${BASE_URL}/user/bootstrap`, {
    headers,
    tags: { name: "GET /user/bootstrap" },
  });
  record(bootstrap, true);
}

/**
 * Login real — o caminho que paga Argon2.
 *
 * Usa as MESMAS contas do setup: registrar contas novas aqui encheria produção
 * de usuários a cada execução.
 *
 * @param {{tokens: string[]}} data Retorno do setup (usado só para o tamanho).
 */
export function authWorkload(data) {
  const accounts = JSON.parse(ACCOUNTS_RAW);
  const account = accounts[__ITER % accounts.length];

  const res = http.post(
    `${BASE_URL}/auth/login`,
    JSON.stringify({ email: account.email, password: account.password }),
    {
      headers: { "Content-Type": "application/json", "X-API-Contract": "v2" },
      tags: { name: "POST /auth/login" },
    },
  );
  record(res, false);
  check(res, {
    "login 200 ou 429 (freio)": (r) => r.status === 200 || r.status === 429,
  });
}

/**
 * Checkout real — no máximo 5 vezes, e paramos na URL.
 *
 * @param {{tokens: string[]}} data Retorno do setup.
 */
export function checkoutWorkload(data) {
  const headers = authHeaders(data);

  const res = http.post(
    `${BASE_URL}/subscriptions/checkout`,
    JSON.stringify({ plan_slug: "premium_monthly" }),
    {
      headers,
      redirects: 0, // nunca visitar a página de pagamento
      tags: { name: "POST /subscriptions/checkout" },
    },
  );
  record(res, false);

  check(res, {
    "checkout respondeu": (r) => r.status === 200 || r.status === 201 || r.status === 429,
  });

  if (res.status === 200 || res.status === 201) {
    const body = res.json();
    const url = body && body.data ? body.data.checkout_url || body.data.url : null;
    console.log(`checkout ${__ITER + 1}/5 → ${url ? "URL recebida" : "sem URL no corpo"}`);
  }

  sleep(5);
}
