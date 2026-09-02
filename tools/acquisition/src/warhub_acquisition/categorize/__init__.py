"""Decide what a product IS, from the taxonomy its own sources publish.

A SEPARATE STAGE, NOT PART OF THE RESOLVER, and the split is the point. `resolve` is a pure
function of the product pipeline's own inputs (evidence + taxonomy + matches + overrides); this
stage additionally reads the PAINT archive, and it reads it live rather than through a committed
index. A committed cross-catalog index was tried in PR #145 and closed unmerged: it goes stale
between the two pipelines' different cadences, and a stale index re-guesses without saying so.

WHY THE DECISION IS NOT MADE AT ACQUIRE TIME, which is where it used to live. A mapping applied
while harvesting bakes itself into the evidence: the raw value it mapped is recorded nowhere, so a
better rule can never be applied to observations already collected, and a table cannot be authored
offline because nothing says what values exist. Storing the store's taxonomy verbatim (PR #147) and
deciding here instead means a rule change is a re-run of this stage over data already in hand.

WHAT IT MAY AND MAY NOT DO. It only ever fills a category the resolver could not source from
evidence at all -- `categoryBasis: unknown`, i.e. the record has none. A `stated` category, and
anything an override set, is left exactly as it is: a source that actually made a claim about one
product outranks any table, and this stage exists to answer open questions, not to re-answer
settled ones.
"""
