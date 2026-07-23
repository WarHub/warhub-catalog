namespace WarHub.Catalog.Publish;

/// <summary>
/// Turns per-brand paint YAML + the cross-brand equivalences file into consolidated +
/// per-brand JSON. Assigns each paint a stable <c>brand-slug/paint-slug</c> id and folds
/// the (bidirectional) Delta-E equivalents into each paint.
/// </summary>
internal static class PaintBuilder
{
    private sealed record Entry(string BrandSlug, string Brand, PaintYaml Paint);

    private static string NaturalKey(string brandSlug, string name, string set, string? code) =>
        $"{brandSlug}|{name}|{set}|{code ?? ""}";

    public static int Build(
        IReadOnlyList<BrandFile> brands,
        EquivFile? equivalences,
        Provenance prov,
        CatalogWriter writer)
    {
        // 1. Flatten, de-duplicating exact natural-key repeats.
        var seen = new HashSet<string>(StringComparer.Ordinal);
        var entries = new List<Entry>();
        foreach (BrandFile brand in brands)
        {
            foreach (PaintYaml p in brand.Paints)
            {
                if (seen.Add(NaturalKey(brand.BrandSlug, p.Name, p.Details.Set, p.ProductCode)))
                {
                    entries.Add(new Entry(brand.BrandSlug, brand.Brand, p));
                }
            }
        }

        // 2. Assign ids: brand-slug/paint-slug, with deterministic -N suffixes on collision.
        var idByNaturalKey = new Dictionary<string, string>(StringComparer.Ordinal);
        var recordById = new Dictionary<string, PaintRecord>(StringComparer.Ordinal);
        var equivById = new Dictionary<string, Dictionary<string, (double DeltaE, string? Tier)>>(StringComparer.Ordinal);

        foreach (IGrouping<string, Entry> group in entries
            .GroupBy(e => $"{e.BrandSlug}/{Slug.Make(e.Paint.Name)}", StringComparer.Ordinal)
            .OrderBy(g => g.Key, StringComparer.Ordinal))
        {
            var ordered = group
                .OrderBy(e => e.Paint.Details.Set, StringComparer.Ordinal)
                .ThenBy(e => e.Paint.ProductCode ?? "", StringComparer.Ordinal)
                .ThenBy(e => e.Paint.Details.Hex, StringComparer.Ordinal)
                .ToList();

            for (int i = 0; i < ordered.Count; i++)
            {
                Entry e = ordered[i];
                string id = i == 0 ? group.Key : $"{group.Key}-{i + 1}";
                idByNaturalKey[NaturalKey(e.BrandSlug, e.Paint.Name, e.Paint.Details.Set, e.Paint.ProductCode)] = id;
                equivById[id] = new Dictionary<string, (double, string?)>(StringComparer.Ordinal);
                recordById[id] = new PaintRecord(
                    Id: id,
                    Brand: e.Brand,
                    Category: e.Paint.Category,
                    Range: string.IsNullOrWhiteSpace(e.Paint.Details.Set) ? null : e.Paint.Details.Set,
                    Name: e.Paint.Name,
                    Hex: NormalizeHex(e.Paint.Details.Hex),
                    Type: e.Paint.Details.Type,
                    Finish: e.Paint.Details.Finish,
                    VolumeMl: e.Paint.Details.VolumeMl,
                    Container: e.Paint.Details.Container,
                    ProductCode: e.Paint.ProductCode,
                    Ean: e.Paint.Ean,
                    Status: e.Paint.Status,
                    Availability: e.Paint.Availability,
                    Equivalents: []); // filled below
            }
        }

        // 3. Fold equivalences in, bidirectionally (keep the smallest Delta-E per pair).
        if (equivalences is not null)
        {
            foreach (EquivEntry entry in equivalences.Equivalences)
            {
                if (!TryResolve(idByNaturalKey, entry.Source, out string sourceId))
                {
                    continue;
                }

                foreach (EquivMatch match in entry.Matches)
                {
                    if (!TryResolve(idByNaturalKey, match.Paint, out string matchId) || matchId == sourceId)
                    {
                        continue;
                    }

                    Link(equivById, sourceId, matchId, match.DeltaE, match.Tier);
                    Link(equivById, matchId, sourceId, match.DeltaE, match.Tier);
                }
            }
        }

        // 4. Materialize records with sorted equivalents.
        foreach ((string id, PaintRecord record) in recordById)
        {
            var eq = equivById[id]
                .Select(kv => new PaintEquivalent(kv.Key, kv.Value.DeltaE, kv.Value.Tier))
                .OrderBy(x => x.DeltaE)
                .ThenBy(x => x.Id, StringComparer.Ordinal)
                .ToList();
            recordById[id] = record with { Equivalents = eq };
        }

        // 5. Partition by brand, write consolidated + partitions + index.
        var byBrand = recordById.Values
            .GroupBy(r => r.Brand, StringComparer.Ordinal)
            .Select(g => (BrandSlug: g.First().Id.Split('/')[0], Brand: g.Key, Paints: g
                .OrderBy(r => r.Id, StringComparer.Ordinal).ToList()))
            .OrderBy(x => x.BrandSlug, StringComparer.Ordinal)
            .ToList();

        var allPaints = byBrand.SelectMany(b => b.Paints)
            .OrderBy(r => r.Id, StringComparer.Ordinal).ToList();
        int total = allPaints.Count;

        writer.Write("paints.json", "paint-catalog", "paint-catalog", null, total,
            new PaintCatalogDocument
            {
                Version = prov.Version,
                GeneratedAt = prov.GeneratedAt,
                GitCommit = prov.GitCommit,
                Counts = new Dictionary<string, int> { ["paints"] = total, ["brands"] = byBrand.Count },
                Source = prov.SourceFor("paints.json"),
                Paints = allPaints,
            });

        var indexEntries = new List<IndexEntry>();
        foreach ((string brandSlug, string brand, List<PaintRecord> paints) in byBrand)
        {
            string relPath = $"paints/by-brand/{brandSlug}.json";
            writer.Write(relPath, "paint-catalog", "paint-catalog-partition", brandSlug, paints.Count,
                new PaintCatalogDocument
                {
                    Kind = "paint-catalog-partition",
                    Version = prov.Version,
                    GeneratedAt = prov.GeneratedAt,
                    GitCommit = prov.GitCommit,
                    Partition = new Partition("brand", brandSlug, brand),
                    Counts = new Dictionary<string, int> { ["paints"] = paints.Count },
                    Source = prov.SourceFor(relPath),
                    Paints = paints,
                });
            indexEntries.Add(new IndexEntry(brandSlug, brand, paints.Count, relPath));
        }

        writer.Write("paints/index.json", "index", "paint-index", null, total,
            new IndexDocument
            {
                Kind = "paint-index",
                Version = prov.Version,
                GeneratedAt = prov.GeneratedAt,
                PartitionType = "brand",
                Total = total,
                Partitions = indexEntries,
            });

        return total;
    }

    private static bool TryResolve(Dictionary<string, string> map, EquivRef refr, out string id) =>
        map.TryGetValue(NaturalKey(refr.BrandSlug, refr.Name, refr.Set, refr.ProductCode), out id!);

    private static void Link(
        Dictionary<string, Dictionary<string, (double, string?)>> adjacency,
        string from, string to, double deltaE, string? tier)
    {
        Dictionary<string, (double, string?)> neighbors = adjacency[from];
        if (!neighbors.TryGetValue(to, out (double DeltaE, string? Tier) existing) || deltaE < existing.DeltaE)
        {
            neighbors[to] = (deltaE, tier);
        }
    }

    private static string NormalizeHex(string hex)
    {
        string h = hex.Trim().ToLowerInvariant();
        return h.StartsWith('#') ? h : $"#{h}";
    }
}
