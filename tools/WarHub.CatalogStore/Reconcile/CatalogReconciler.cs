namespace WarHub.CatalogStore.Reconcile;

/// <summary>Merged records (sorted by identity key) plus the keys seen this run.</summary>
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

        foreach (T freshRec in fresh)
        {
            string freshKey = adapter.IdentityKey(freshRec);

            // 1. Composite key match.
            if (byKey.TryGetValue(freshKey, out T? existingByKey))
            {
                byKey[freshKey] = adapter.Merge(existingByKey, freshRec);
                seen.Add(freshKey);
                continue;
            }

            // 2. URL fallback → rename.
            string? freshUrl = adapter.Url(freshRec);
            if (!string.IsNullOrEmpty(freshUrl) && byUrl.TryGetValue(freshUrl, out string? renamedKey)
                && byKey.TryGetValue(renamedKey, out T? existingByUrl))
            {
                byKey.Remove(renamedKey);
                T renamed = adapter.ApplyRename(existingByUrl, freshRec);
                byKey[freshKey] = renamed;
                seen.Add(freshKey);
                continue;
            }

            // 3. Alias override → rename (freshKey -> canonical existing key).
            if (aliases.TryGetValue(freshKey, out string? canonicalKey)
                && byKey.TryGetValue(canonicalKey, out T? existingByAlias))
            {
                byKey.Remove(canonicalKey);
                T renamed = adapter.ApplyRename(existingByAlias, freshRec);
                byKey[freshKey] = renamed;
                seen.Add(freshKey);
                continue;
            }

            // 4. New record.
            T inserted = adapter.HasFirstSeen(freshRec) ? freshRec : adapter.WithFirstSeen(freshRec, today);
            byKey[freshKey] = inserted;
            seen.Add(freshKey);
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
