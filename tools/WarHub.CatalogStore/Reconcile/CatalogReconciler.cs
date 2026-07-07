namespace WarHub.CatalogStore.Reconcile;

/// <summary>Merged records (sorted by identity key) plus the keys seen this run.</summary>
/// <remarks><see cref="SeenKeys"/> are identity keys matched or inserted this run and are NOT guaranteed to all appear in <see cref="Records"/> (a key can be seen yet removed by <c>retracted</c>).</remarks>
public sealed record ReconcileResult<T>(IReadOnlyList<T> Records, IReadOnlySet<string> SeenKeys);

/// <summary>
/// Append-only, backfill-only reconciliation of a fresh scrape against the
/// archived records for one set (a faction file). Never drops archived records
/// except via the explicit retract set. Deterministic output order.
/// </summary>
public sealed class CatalogReconciler<T>(ICatalogRecordAdapter<T> adapter)
{
    public ReconcileResult<T> Reconcile(
        IReadOnlyList<T> existing,
        IReadOnlyList<T> fresh,
        IReadOnlyDictionary<string, string> aliases,
        ISet<string> retracted,
        string today)
    {
        // Index existing by identity key and by URL (first wins on URL collisions).
        var byKey = new Dictionary<string, T>(StringComparer.Ordinal);
        var byUrl = new Dictionary<string, string>(StringComparer.Ordinal); // url -> identity key
        foreach (T rec in existing)
        {
            string key = adapter.IdentityKey(rec);
            byKey[key] = rec;
            string? url = adapter.Url(rec);
            if (!string.IsNullOrEmpty(url))
                byUrl.TryAdd(url, key);
        }

        var seen = new HashSet<string>(StringComparer.Ordinal);
        // Keys already matched or inserted this run cannot be re-consumed by a later
        // fresh record's URL/alias fallback — this prevents two distinct fresh records
        // that happen to share a URL/alias from collapsing into one output record.
        var consumed = new HashSet<string>(StringComparer.Ordinal);

        foreach (T freshRec in fresh)
        {
            string freshKey = adapter.IdentityKey(freshRec);

            // 1. Composite key match.
            if (byKey.TryGetValue(freshKey, out T? existingByKey))
            {
                byKey[freshKey] = adapter.Merge(existingByKey, freshRec);
                seen.Add(freshKey);
                consumed.Add(freshKey);
                continue;
            }

            // 2. URL fallback → rename (only if the target has not been consumed this run).
            string? freshUrl = adapter.Url(freshRec);
            if (!string.IsNullOrEmpty(freshUrl) && byUrl.TryGetValue(freshUrl, out string? renamedKey)
                && !consumed.Contains(renamedKey)
                && byKey.TryGetValue(renamedKey, out T? existingByUrl))
            {
                byKey.Remove(renamedKey);
                byKey[freshKey] = adapter.ApplyRename(existingByUrl, freshRec);
                seen.Add(freshKey);
                consumed.Add(renamedKey);
                consumed.Add(freshKey);
                continue;
            }

            // 3. Alias override → rename (only if the canonical target has not been consumed).
            if (aliases.TryGetValue(freshKey, out string? canonicalKey)
                && !consumed.Contains(canonicalKey)
                && byKey.TryGetValue(canonicalKey, out T? existingByAlias))
            {
                byKey.Remove(canonicalKey);
                byKey[freshKey] = adapter.ApplyRename(existingByAlias, freshRec);
                seen.Add(freshKey);
                consumed.Add(canonicalKey);
                consumed.Add(freshKey);
                continue;
            }

            // 4. New record.
            T inserted = adapter.HasFirstSeen(freshRec) ? freshRec : adapter.WithFirstSeen(freshRec, today);
            byKey[freshKey] = inserted;
            seen.Add(freshKey);
            consumed.Add(freshKey);
        }

        // Apply retractions, then order deterministically.
        var ordered = byKey
            .Where(kvp => !retracted.Contains(kvp.Key))
            .OrderBy(kvp => kvp.Key, StringComparer.Ordinal)
            .Select(kvp => kvp.Value)
            .ToList();

        return new ReconcileResult<T>(ordered, seen);
    }
}
