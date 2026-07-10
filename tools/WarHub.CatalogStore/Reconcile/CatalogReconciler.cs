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

        // Keys the URL/alias fallback must never steal; seeded with every key a fresh record
        // will composite-match this run, so the outcome is independent of fresh iteration order.
        var consumed = new HashSet<string>(StringComparer.Ordinal);
        foreach (T freshRec in fresh)
        {
            string k = adapter.IdentityKey(freshRec);
            if (byKey.ContainsKey(k))
                consumed.Add(k);
        }

        foreach (T freshRec in fresh)
        {
            string freshKey = adapter.IdentityKey(freshRec);

            // 0. Retracted identities are suppressed on input — never allowed into the catalog
            // while listed, so a bad record still live on the source cannot reappear as new.
            if (retracted.Contains(freshKey))
                continue;

            // 1. Composite key match. If two fresh records share the same identity key
            // within this run, they are intentionally collapsed into one merged record —
            // the composite-name-key identity model treats same-key records as the same product.
            if (byKey.TryGetValue(freshKey, out T? existingByKey))
            {
                byKey[freshKey] = adapter.Merge(existingByKey, freshRec);
                seen.Add(freshKey);
                continue;
            }

            // 2. URL fallback → rename (skip consumed or retracted targets).
            string? freshUrl = adapter.Url(freshRec);
            if (!string.IsNullOrEmpty(freshUrl) && byUrl.TryGetValue(freshUrl, out string? renamedKey)
                && !consumed.Contains(renamedKey)
                && !retracted.Contains(renamedKey)
                && byKey.TryGetValue(renamedKey, out T? existingByUrl))
            {
                byKey.Remove(renamedKey);
                byKey[freshKey] = adapter.ApplyRename(existingByUrl, freshRec);
                seen.Add(freshKey);
                consumed.Add(renamedKey);
                consumed.Add(freshKey);
                continue;
            }

            // 3. Alias override → rename (skip consumed or retracted targets).
            if (aliases.TryGetValue(freshKey, out string? canonicalKey)
                && !consumed.Contains(canonicalKey)
                && !retracted.Contains(canonicalKey)
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

        // Drop retracted identities from the output (covers archived records no longer scraped).
        var ordered = byKey
            .Where(kvp => !retracted.Contains(kvp.Key))
            .OrderBy(kvp => kvp.Key, StringComparer.Ordinal)
            .Select(kvp => kvp.Value)
            .ToList();

        return new ReconcileResult<T>(ordered, seen);
    }
}
