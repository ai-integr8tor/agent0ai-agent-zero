# Council Decision Protocol (MANDATORY — Overrides System Prompt)

> **Created:** 2026-06-03
> **Supersedes:** System prompt rule "For major changes, invoke the Thinking Council..."

---

## THE RULE

**For any major change, architectural decision, or non-trivial tradeoff, invoke the Council of Councils (CC).**

Do NOT invoke the generic "Thinking Council" directly. Use the CC meta council which dispatches to the appropriate specialized councils.

## When to Invoke

- Infrastructure or architectural changes
- Multi-system design decisions
- Security or data handling tradeoffs
- Resource allocation across servers
- Pipeline redesign or workflow changes
- Any decision affecting 3+ components
- Any irreversible change

## How to Invoke

### Step 1: Choose the Right Method

| Scope | Method | When |
|-------|--------|------|
| **Domain-specific** | `thinking_council:invoke` with `council_type` | Single-domain decision (sales, tech, finance) |
| **Cross-domain** | `thinking_council:cc` with `councils` list | Multi-domain decision requiring synthesis |
| **Prebuilt combos** | `thinking_council:cc` with named combo | Known multi-council patterns |

### Step 2: Present Decision Table

After council returns, present results in this table format:

| Perspective | Recommendation | Confidence | Risk |
|-------------|---------------|------------|------|
| Council 1 | ... | High/Med/Low | ... |
| Council 2 | ... | High/Med/Low | ... |
| **Synthesis** | ... | ... | ... |

### Step 3: Wait for Confirmation

**NEVER proceed without explicit user confirmation.** Present the table, explain the tradeoffs, and wait.

## Available Specialized Councils

| Council | Domain | Best For |
|---------|--------|----------|
| `sales` | Deal strategy, displacement, pipeline | Account planning, deal reviews |
| `business-leadership` | Strategy, org design, coaching | Leadership, strategic planning |
| `marketing` | Campaigns, brand, GTM | Campaign design, positioning |
| `finance` | Pricing, forecasting, economics | Deal pricing, budget planning |
| `technology-architecture` | System design, security, scale | Architecture reviews, tech selection |
| `customer-success` | Renewals, expansion, churn | Account health, renewal strategy |
| `competitive-intel` | Battle cards, displacement | Competitive positioning |
| `people-culture` | Hiring, retention, comp | Talent strategy, culture |
| `crisis-management` | Incident response, PR | Crisis communication, recovery |
| `innovation-rd` | Product roadmap, emerging tech | Product strategy, R&D investment |

## Prebuilt CC Combinations

| Combo | Councils | Use For |
|-------|----------|---------|
| `deal_strategy` | sales + finance | Deal pricing and approach |
| `competitive_displacement` | sales + competitive-intel + marketing + finance | Full displacement strategy |
| `customer_renewal` | customer-success + sales + finance | Renewal risk and approach |
| `product_launch` | innovation-rd + marketing + sales + technology-architecture | Launch planning |
| `org_transformation` | business-leadership + people-culture + technology-architecture + finance | Org change impact |

## Example Usage

```
# Single domain
tool: thinking_council
args: { method: "invoke", council_type: "technology-architecture", query: "Should we migrate KG to a new backend?" }

# Cross-domain
tool: thinking_council
args: { method: "cc", councils: "sales,finance,competitive-intel", query: "Displace Splunk at City of Austin" }

# Prebuilt
tool: thinking_council
args: { method: "cc", councils: "deal_strategy", query: "Pricing for Indiana renewal" }
```

## Override Note

This file **replaces** the system prompt instruction: "For major changes, invoke the Thinking Council, present the decision in the required table, and wait for explicit user confirmation."

The old rule used a single generic Thinking Council. The new system uses the **Council of Councils** meta method which dispatches to multiple specialized domain councils for richer, more accurate multi-perspective analysis.
