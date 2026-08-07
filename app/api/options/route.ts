import { timingSafeEqual } from "node:crypto";
import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 10;

const MAX_BODY_BYTES = 256 * 1024;
const EXPECTED_SCHEMA = "options-box-spread.v1";

type Opportunity = {
  true_net_profit_cny: number;
  absolute_gross_profit_cny: number;
  fees_cny: number;
  slippage_cny: number;
  contract_multiplier: number;
  legs: unknown[];
  [key: string]: unknown;
};

type PushPayload = {
  schema_version: string;
  generated_at: string;
  source: string;
  opportunity_count: number;
  assumptions: Record<string, unknown>;
  opportunities: Opportunity[];
};

function constantTimeSecretEquals(received: string, expected: string): boolean {
  const left = Buffer.from(received, "utf8");
  const right = Buffer.from(expected, "utf8");
  return left.length === right.length && timingSafeEqual(left, right);
}
function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isValidOpportunity(value: unknown): value is Opportunity {
  if (!value || typeof value !== "object") return false;
  const item = value as Record<string, unknown>;
  return (
    isFiniteNumber(item.true_net_profit_cny) &&
    item.true_net_profit_cny > 0 &&
    isFiniteNumber(item.absolute_gross_profit_cny) &&
    isFiniteNumber(item.fees_cny) &&
    item.fees_cny === 6.8 &&
    isFiniteNumber(item.slippage_cny) &&
    item.slippage_cny === 4.0 &&
    item.contract_multiplier === 10_000 &&
    Array.isArray(item.legs) &&
    item.legs.length === 4
  );
}

function isValidPayload(value: unknown): value is PushPayload {
  if (!value || typeof value !== "object") return false;
  const payload = value as Record<string, unknown>;
  if (
    payload.schema_version !== EXPECTED_SCHEMA ||
    typeof payload.generated_at !== "string" ||
    typeof payload.source !== "string" ||
    !Number.isInteger(payload.opportunity_count) ||
    !Array.isArray(payload.opportunities) ||
    payload.opportunity_count !== payload.opportunities.length ||
    payload.opportunities.length > 500
  ) {
    return false;
  }
  // Reject, rather than silently filter, any payload containing a non-positive
  // or dimensionally inconsistent opportunity.
  return payload.opportunities.every(isValidOpportunity);
}

export async function POST(request: NextRequest): Promise<NextResponse> {
  const expectedSecret = process.env.OPTIONS_WEBHOOK_SECRET ?? "";
  const headerName = (process.env.OPTIONS_SECRET_HEADER ?? "x-options-secret").toLowerCase();
  const receivedSecret = request.headers.get(headerName) ?? "";
  if (!expectedSecret || !constantTimeSecretEquals(receivedSecret, expectedSecret)) {
    return NextResponse.json({ ok: false, error: "unauthorized" }, { status: 401 });
  }

  const contentLength = Number(request.headers.get("content-length") ?? "0");
  if (!Number.isFinite(contentLength) || contentLength <= 0 || contentLength > MAX_BODY_BYTES) {
    return NextResponse.json({ ok: false, error: "invalid body size" }, { status: 413 });
  }

  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json({ ok: false, error: "invalid JSON" }, { status: 400 });
  }
  if (!isValidPayload(payload)) {
    return NextResponse.json(
      { ok: false, error: "invalid or non-positive opportunity payload" },
      { status: 422 },
    );
  }

  // This route acknowledges ingestion only. Vercel function memory is not
  // durable; attach a database here if historical persistence is required.
  return NextResponse.json(
    {
      ok: true,
      accepted: payload.opportunities.length,
      received_at: new Date().toISOString(),
    },
    { status: 200, headers: { "Cache-Control": "no-store" } },
  );
}
