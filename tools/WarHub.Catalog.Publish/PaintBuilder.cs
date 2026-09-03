namespace WarHub.Catalog.Publish;

/// <summary>
/// Turns per-brand paint YAML + the cross-brand equivalences file into consolidated +
/// per-brand JSON. Assigns each paint a stable <c>brand-slug/paint-slug</c> id and folds
/// the (bidirectional) Delta-E equivalents into each paint.
/// </summary>
internal static class PaintBuilder
{
    private sealed record Entry(string BrandSlug, string Brand, PaintYaml Paint);

    // Hex is part of the key because it is part of a paint's IDENTITY upstream
    // (PaintRecordAdapter.IdentityKey = set|name|productCode|hex). Without it, two records that
    // share brand|name|set|code but are DIFFERENT COLOURS -- a reformulation, or a colour
    // correction -- collided here and the second was silently dropped at step 1 below, never
    // published (measured: 2 real paints, Kommando Khaki and Vallejo Viking Grey).
    // This needs NO regeneration of equivalences.yaml: every ref in that file already carries a
    // hex, it was just parsed and discarded (see EquivRef.Hex). Both sides normalize identically
    // via NormalizeHex so '#9B8C7B' and '#9b8c7b' are the same key.
    private static string NaturalKey(string brandSlug, string name, string set, string? code, string? hex) =>
        $"{brandSlug}|{name}|{set}|{code ?? ""}|{NormalizeHex(hex ?? "") ?? ""}";

    /// <summary>
    /// Assemble + write in one step, with no cross-catalog links. Kept for callers that publish
    /// paints on their own; <see cref="Publisher"/> uses the two phases separately so the barcode
    /// link pass can run between them.
    /// </summary>
    // Lineage is stored upstream as `{Name}|{Set}` -- the cross-reference key the paint tool uses
    // everywhere (overrides, the barcode bridge, harvest enrichment). It is NOT the natural key:
    // it omits code and hex, so it can be ambiguous (variant ranges legitimately ship one colour
    // name under several codes). Ambiguous keys are dropped from the map below rather than guessed.
    private static string LineageKey(string brandSlug, string name, string set) =>
        $"{brandSlug}|{name}|{set}";

    public static int Build(
        IReadOnlyList<BrandFile> brands,
        EquivFile? equivalences,
        Provenance prov,
        CatalogWriter writer) => Write(Assemble(brands, equivalences), prov, writer);

    /// <summary>
    /// Runs steps 1-4 (flatten, assign ids, fold equivalences, materialize) and stops before
    /// serialization, so the cross-catalog link pass can stamp <c>productIds</c> on. The id
    /// assignment in step 2 is what the product side links AGAINST, so it has to have happened
    /// before any link can be computed.
    /// </summary>
    public static PaintAssembly Assemble(IReadOnlyList<BrandFile> brands, EquivFile? equivalences)
    {
        // 1. Flatten, de-duplicating exact natural-key repeats.
        var seen = new HashSet<string>(StringComparer.Ordinal);
        var entries = new List<Entry>();
        foreach (BrandFile brand in brands)
        {
            foreach (PaintYaml p in brand.Paints)
            {
                if (seen.Add(NaturalKey(brand.BrandSlug, p.Name, p.Details.Set, p.ProductCode, p.Details.Hex)))
                {
                    entries.Add(new Entry(brand.BrandSlug, brand.Brand, p));
                }
            }
        }

        // 2. Assign ids: brand-slug/paint-slug, QUALIFIED BY CONTENT when the name collides.
        //
        // The suffix used to be positional -- sort the colliding group by (set, code, hex) and
        // append -2, -3 by index. That made an id a statement about the group's membership rather
        // than about the paint: inserting one paint renumbered its siblings, and 1,541 records
        // (18%) carried such a suffix. Minting the two Contrast reformulations made the failure
        // concrete -- "Contrast" sorts before "Technical", so `citadel-colour/hexwraith-flame`
        // silently STOPPED meaning the Technical pot and started meaning the Contrast one.
        //
        // The suffix is now derived from the paint's own identity (set, then product code, then
        // hex -- the same fields as the natural key), so an id depends on nothing but the paint it
        // names. When a name collides, EVERY member is qualified and none keeps the bare id: a
        // consumer holding the old bare id gets a clean 404 instead of silently the wrong colour.
        // Uncollided names -- the large majority -- are untouched.
        var idByNaturalKey = new Dictionary<string, string>(StringComparer.Ordinal);
        var recordById = new Dictionary<string, PaintRecord>(StringComparer.Ordinal);
        var equivById = new Dictionary<string, Dictionary<string, (double DeltaE, string? Tier)>>(StringComparer.Ordinal);
        // `{brand}|{name}|{set}` -> id, with null marking an ambiguous key (see LineageKey).
        var idByLineageKey = new Dictionary<string, string?>(StringComparer.OrdinalIgnoreCase);

        static string Natural(Entry e) =>
            NaturalKey(e.BrandSlug, e.Paint.Name, e.Paint.Details.Set, e.Paint.ProductCode, e.Paint.Details.Hex);

        foreach (IGrouping<string, Entry> group in entries
            .GroupBy(e => $"{e.BrandSlug}/{Slug.Make(e.Paint.Name)}", StringComparer.Ordinal)
            .OrderBy(g => g.Key, StringComparer.Ordinal))
        {
            var ordered = group
                .OrderBy(e => e.Paint.Details.Set, StringComparer.Ordinal)
                .ThenBy(e => e.Paint.ProductCode ?? "", StringComparer.Ordinal)
                .ThenBy(e => e.Paint.Details.Hex, StringComparer.Ordinal)
                .ToList();

            // Qualify only when the bare name is contested, and only as far as it takes to be
            // unique: set, then + product code, then + hex. Those are exactly the natural key's
            // fields, so a fully-qualified id cannot collide -- two records that reached here with
            // the same set, code AND hex would already have been folded by the natural key above.
            var qualified = new Dictionary<string, string>(StringComparer.Ordinal);
            if (ordered.Count > 1)
            {
                foreach (Entry e in ordered)
                {
                    qualified[Natural(e)] = $"{group.Key}-{Slug.Make(e.Paint.Details.Set)}";
                }
                for (int level = 0; level < 2; level++)
                {
                    var clashing = qualified.GroupBy(kv => kv.Value, StringComparer.Ordinal)
                        .Where(g => g.Count() > 1)
                        .SelectMany(g => g.Select(kv => kv.Key))
                        .ToHashSet(StringComparer.Ordinal);
                    if (clashing.Count == 0)
                    {
                        break;
                    }
                    foreach (Entry e in ordered.Where(x => clashing.Contains(Natural(x))))
                    {
                        string extra = level == 0
                            ? Slug.Make(e.Paint.ProductCode ?? "")
                            : (NormalizeHex(e.Paint.Details.Hex) ?? "").TrimStart('#').ToLowerInvariant();
                        if (extra.Length > 0)
                        {
                            qualified[Natural(e)] = $"{qualified[Natural(e)]}-{extra}";
                        }
                    }
                }
            }

            for (int i = 0; i < ordered.Count; i++)
            {
                Entry e = ordered[i];
                string naturalKey = Natural(e);
                string id = qualified.TryGetValue(naturalKey, out string? q) ? q : group.Key;
                // A duplicate id here SILENTLY DROPS a paint via the dictionary write below.
                // That is not hypothetical: the previous positional scheme lost 4 records
                // this way, because a name legitimately ending in a digit could collide with
                // another name's `-2`. Fail the build instead.
                if (recordById.ContainsKey(id))
                {
                    throw new InvalidOperationException(
                        $"duplicate paint id '{id}' -- two paints would publish under one id");
                }
                idByNaturalKey[NaturalKey(e.BrandSlug, e.Paint.Name, e.Paint.Details.Set, e.Paint.ProductCode, e.Paint.Details.Hex)] = id;
                string lineageKey = LineageKey(e.BrandSlug, e.Paint.Name, e.Paint.Details.Set);
                idByLineageKey[lineageKey] = idByLineageKey.ContainsKey(lineageKey) ? null : id;
                equivById[id] = new Dictionary<string, (double, string?)>(StringComparer.Ordinal);
                recordById[id] = new PaintRecord(
                    Id: id,
                    Brand: e.Brand,
                    Category: e.Paint.Category,
                    Role: Trimmed(e.Paint.Role),
                    Range: string.IsNullOrWhiteSpace(e.Paint.Details.Set) ? null : e.Paint.Details.Set,
                    Name: e.Paint.Name,
                    Hex: NormalizeHex(e.Paint.Details.Hex),
                    Type: e.Paint.Details.Type,
                    Finish: e.Paint.Details.Finish,
                    VolumeMl: e.Paint.Details.VolumeMl,
                    WeightG: e.Paint.Details.WeightG,
                    Container: e.Paint.Details.Container,
                    ProductCode: e.Paint.ProductCode,
                    Ean: e.Paint.Ean,
                    AdditionalEans: e.Paint.AdditionalEans is { Count: > 0 } extra ? extra : null,
                    ImageUrl: Trimmed(e.Paint.ImageUrl),
                    PriceGbp: e.Paint.PriceGbp,
                    PriceUsd: e.Paint.PriceUsd,
                    PriceEur: e.Paint.PriceEur,
                    PriceCad: e.Paint.PriceCad,
                    Status: e.Paint.Status,
                    Availability: e.Paint.Availability,
                    SoldSeparately: e.Paint.SoldSeparately,
                    Colourless: e.Paint.Colourless,
                    // Still the upstream `{Name}|{Set}` keys here; rewritten to ids in step 4.
                    Supersedes: e.Paint.Supersedes is { Count: > 0 } prior ? prior : null,
                    SupersededBy: Trimmed(e.Paint.SupersededBy),
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

        // 4. Materialize records with sorted equivalents and resolved lineage.
        foreach ((string id, PaintRecord record) in recordById)
        {
            var eq = equivById[id]
                .Select(kv => new PaintEquivalent(kv.Key, kv.Value.DeltaE, kv.Value.Tier))
                .OrderBy(x => x.DeltaE)
                .ThenBy(x => x.Id, StringComparer.Ordinal)
                .ToList();

            string brandSlug = id.Split('/')[0];
            var supersedes = record.Supersedes?
                .Select(key => ResolveLineage(idByLineageKey, brandSlug, key, id))
                .OfType<string>()
                .Distinct(StringComparer.Ordinal)
                .OrderBy(x => x, StringComparer.Ordinal)
                .ToList();

            recordById[id] = record with
            {
                Equivalents = eq,
                Supersedes = supersedes is { Count: > 0 } ? supersedes : null,
                SupersededBy = ResolveLineage(idByLineageKey, brandSlug, record.SupersededBy, id),
            };
        }

        return new PaintAssembly(recordById);
    }

    /// <summary>Step 5: partition by brand, write consolidated + partitions + index.</summary>
    public static int Write(PaintAssembly assembly, Provenance prov, CatalogWriter writer)
    {
        var byBrand = assembly.Records
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

    /// <summary>
    /// Turns one upstream <c>{Name}|{Set}</c> lineage key into a published paint id, within the
    /// SAME brand (a reformulation never crosses brands). Returns null — the link is simply not
    /// published — when the key names nothing, names several paints (see <see cref="LineageKey"/>),
    /// or names the record itself. A dangling id in the published catalog would be worse than a
    /// missing one: consumers treat these as resolvable.
    /// </summary>
    private static string? ResolveLineage(
        Dictionary<string, string?> idByLineageKey, string brandSlug, string? key, string selfId)
    {
        if (string.IsNullOrWhiteSpace(key))
            return null;
        return idByLineageKey.TryGetValue($"{brandSlug}|{key.Trim()}", out string? id) && id != selfId
            ? id
            : null;
    }

    private static string? Trimmed(string? value) =>
        string.IsNullOrWhiteSpace(value) ? null : value.Trim();

    private static bool TryResolve(Dictionary<string, string> map, EquivRef refr, out string id) =>
        map.TryGetValue(NaturalKey(refr.BrandSlug, refr.Name, refr.Set, refr.ProductCode, refr.Hex), out id!);

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

    private static string? NormalizeHex(string hex)
    {
        string h = hex.Trim().ToLowerInvariant();
        // Harvested additions can carry no colour yet (hex unknown until an override or a
        // swatch-extraction pass fills it) -- publish them with NO hex property at all
        // (null serializes as omitted), never "" or a bare "#": the schema pattern applies
        // only when the property is present.
        if (h.Length == 0)
            return null;
        return h.StartsWith('#') ? h : $"#{h}";
    }
}

/// <summary>
/// Paints built and keyed by their assigned id, but not yet serialized -- the handoff between
/// <see cref="PaintBuilder.Assemble"/> and <see cref="PaintBuilder.Write"/>. Brand partitions and
/// the consolidated order are still derived at write time from these records, unchanged.
/// </summary>
internal sealed class PaintAssembly(Dictionary<string, PaintRecord> recordById)
{
    public IEnumerable<PaintRecord> Records => recordById.Values;

    /// <summary>
    /// Rewrites every record. Records are immutable, so a link pass replaces them rather than
    /// mutating them; keys are snapshotted first so the dictionary is not enumerated while written.
    /// </summary>
    public void MapRecords(Func<PaintRecord, PaintRecord> map)
    {
        foreach (string id in recordById.Keys.ToList())
        {
            recordById[id] = map(recordById[id]);
        }
    }
}
