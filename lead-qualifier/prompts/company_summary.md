You are a B2B research analyst. Based ONLY on the website content provided
below, summarise what this company does. Do not invent facts; if something is
unknown, leave it blank or say "unknown".

Company domain: {domain}
Company name (may be unknown): {company_name}

WEBSITE CONTENT (multiple pages, truncated):
{corpus}

Return ONLY a single JSON object (no prose, no markdown fences) with this exact shape:
{{
  "summary": "1-3 sentence plain-language description of what the company does and who it serves",
  "industry": "the company's primary industry/vertical",
  "products_services": ["key product or service 1", "key product or service 2"],
  "size_stage_signals": "any signals about company size, stage, funding, employee count, growth (or 'unknown')"
}}
