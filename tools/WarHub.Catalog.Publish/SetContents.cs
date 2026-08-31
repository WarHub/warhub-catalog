namespace WarHub.Catalog.Publish;

/// <summary>
/// The boxed-set relation: which paints are inside which product.
///
/// THE JOIN IS DONE TWICE, ON PURPOSE, AND THIS IS THE SECOND HALF. Upstream,
/// gen_set_contents.py resolves every <c>contentSkus</c> ref against the paint archive and writes
/// what it found to data/catalog/set-contents/ -- but it can only name a paint by its IDENTITY
/// ({Name}|{Set} plus productCode), never by its id, because ids do not exist until publish time.
/// This type closes that last hop: it turns each identity into the id PaintBuilder just minted.
/// It is the only component that can, because it is the only one holding both catalogs at once.
///
/// THE LOOKUP KEY IS BUILT WITHOUT PARSING. A member's <c>paint</c> field already IS the
/// "{Name}|{Set}" pair, so the key is `{brand}|{paint}|{productCode}` by concatenation rather than
/// by splitting on '|' -- which means a paint whose NAME contains a pipe cannot be mis-split here.
/// Those are exactly the fields upstream joined on (HarvestApplier.ApplyEnrichment's tie-break),
/// so the two halves cannot drift apart in what they consider one paint.
///
/// HEX IS THE ONE FIELD THE KEY OMITS that PaintBuilder.NaturalKey carries, so this key CAN be
/// ambiguous where the natural key is not: two records sharing brand|name|set|code and differing
/// only in colour. Two such pairs exist in the archive today (Kommando Khaki, Viking Grey) and no
/// set member reaches either, but an ambiguous key is REFUSED rather than resolved to whichever
/// record was seen first -- the same rule PaintBuilder.ResolveLineage applies to lineage keys, for
/// the same reason: a dangling reference is recoverable and a confidently wrong one is not.
///
/// A REFUSAL IS PUBLISHED, NEVER DROPPED. Refs the upstream generator could not resolve arrive
/// already carrying their reason and are passed through verbatim; a ref this stage cannot resolve
/// joins them with a reason naming THIS stage. Both land in the same <c>unresolved</c> array, so
/// `members + unresolved == refs` holds in dist/ exactly as it does in the source files, and a set
/// that lists 7 of its 8 colours can never be mistaken for a set that has 7.
/// </summary>
internal sealed class SetContents
{
    private SetContents(
        IReadOnlyDictionary<string, SetRecord> sets,
        int members,
        int unresolvedUpstream,
        int unresolvedAtPublish,
        int paints,
        int setsWithoutProduct)
    {
        Sets = sets;
        Members = members;
        UnresolvedUpstream = unresolvedUpstream;
        UnresolvedAtPublish = unresolvedAtPublish;
        Paints = paints;
        SetsWithoutProduct = setsWithoutProduct;
    }

    /// <summary>Product id -> what is in that box, keys ordinally sorted.</summary>
    public IReadOnlyDictionary<string, SetRecord> Sets { get; }

    /// <summary>Boxed sets published.</summary>
    public int Total => Sets.Count;

    /// <summary>Refs resolved all the way to a published paint id.</summary>
    public int Members { get; }

    /// <summary>Refs the upstream generator refused, carried through with its reason.</summary>
    public int UnresolvedUpstream { get; }

    /// <summary>
    /// Refs upstream resolved that this stage could not turn into a published paint id -- the
    /// paint moved, was withdrawn, or its identity became ambiguous between the two runs. Counted
    /// on its own because it means the two catalogs have drifted, which is a different problem
    /// from a source that never named a resolvable paint.
    /// </summary>
    public int UnresolvedAtPublish { get; }

    /// <summary>Distinct paints reachable through this relation.</summary>
    public int Paints { get; }

    /// <summary>
    /// Sets dropped because no published product carries their id. Publishing one would put a
    /// dangling key in a document whose whole purpose is to be looked up by product id.
    /// </summary>
    public int SetsWithoutProduct { get; }

    /// <summary>Every ref that reached this relation, resolved or not.</summary>
    public int Refs => Members + UnresolvedUpstream + UnresolvedAtPublish;

    public static SetContents Build(
        IReadOnlyDictionary<string, CanonicalSetContentsFile> files,
        IEnumerable<ProductRecord> products,
        IEnumerable<PaintRecord> paints)
    {
        Dictionary<string, string?> paintIdByIdentity = IndexPaints(paints);
        var productIds = new HashSet<string>(products.Select(p => p.Id), StringComparer.Ordinal);

        var sets = new Dictionary<string, SetRecord>(StringComparer.Ordinal);
        var reachedPaints = new HashSet<string>(StringComparer.Ordinal);
        int members = 0, unresolvedUpstream = 0, unresolvedAtPublish = 0, setsWithoutProduct = 0;

        foreach ((string manufacturer, CanonicalSetContentsFile file) in files
            .OrderBy(kv => kv.Key, StringComparer.Ordinal))
        {
            Dictionary<string, CanonicalSet> declared = file.Sets ?? [];
            VerifyCounts(manufacturer, file.Counts, declared);

            foreach ((string productId, CanonicalSet set) in declared
                .OrderBy(kv => kv.Key, StringComparer.Ordinal))
            {
                if (!productIds.Contains(productId))
                {
                    setsWithoutProduct++;
                    continue;
                }

                var resolved = new List<SetMemberRecord>();
                var refused = new List<UnresolvedRef>();

                // Source order is kept: for a `stated` set that is the manufacturer's own array
                // order and for a `description` set it is the order the codes appear in its prose.
                // Both are the source's statement about its own box, and the input is a generated,
                // committed file, so this is deterministic without imposing an order of our own.
                foreach (CanonicalSetMember member in set.Members ?? [])
                {
                    string identity = $"{member.Brand}|{member.Paint}|{member.ProductCode ?? ""}";
                    if (!paintIdByIdentity.TryGetValue(identity, out string? paintId))
                    {
                        refused.Add(new UnresolvedRef(
                            member.Ref,
                            $"upstream resolved this ref to '{member.Paint}' (productCode "
                            + $"'{member.ProductCode ?? ""}') in brand '{member.Brand}', but this release "
                            + "publishes no paint with that identity -- the paint catalog and the "
                            + "set-contents relation were built from different data"));
                        unresolvedAtPublish++;
                        continue;
                    }

                    if (paintId is null)
                    {
                        refused.Add(new UnresolvedRef(
                            member.Ref,
                            $"'{member.Paint}' (productCode '{member.ProductCode ?? ""}') names more than "
                            + $"one published paint in brand '{member.Brand}' -- they differ only by hex, "
                            + "which this relation does not carry, so the ref is refused rather than "
                            + "resolved to an arbitrary one of them"));
                        unresolvedAtPublish++;
                        continue;
                    }

                    resolved.Add(new SetMemberRecord(
                        paintId, member.Ref, member.Quantity, member.ResolvedBy, member.StatedName));
                    reachedPaints.Add(paintId);
                    members++;
                }

                foreach (CanonicalSetUnresolved entry in set.Unresolved ?? [])
                {
                    refused.Add(new UnresolvedRef(entry.Ref, entry.Reason));
                    unresolvedUpstream++;
                }

                sets[productId] = new SetRecord
                {
                    Name = set.Name,
                    ContentSkusFrom = set.From,
                    Members = resolved,
                    Unresolved = refused.Count > 0 ? refused : null,
                };
            }
        }

        return new SetContents(
            sets, members, unresolvedUpstream, unresolvedAtPublish, reachedPaints.Count, setsWithoutProduct);
    }

    public SetContentsDocument ToDocument(Provenance prov, string relPath) => new()
    {
        Version = prov.Version,
        GeneratedAt = prov.GeneratedAt,
        GitCommit = prov.GitCommit,
        Counts = new Dictionary<string, int>
        {
            ["sets"] = Total,
            ["refs"] = Refs,
            ["members"] = Members,
            ["paints"] = Paints,
            ["unresolved"] = UnresolvedUpstream + UnresolvedAtPublish,
            // Split out because the two have different owners: an upstream refusal is fixed by
            // acquiring a paint or minting a set-exclusive one, a publish-time refusal is fixed by
            // rebuilding the relation against the paint archive this release actually ships.
            ["unresolvedAtPublish"] = UnresolvedAtPublish,
        },
        Source = prov.SourceFor(relPath),
        Sets = Sets,
    };

    /// <summary>
    /// <c>{brandSlug}|{Name}|{Set}|{productCode}</c> -> paint id, with null marking a key that
    /// names several paints. The brand slug is the id's first segment rather than the record's
    /// display <c>brand</c>: the display name is "AK Interactive" where the archive and the
    /// relation both say "ak-interactive".
    /// </summary>
    private static Dictionary<string, string?> IndexPaints(IEnumerable<PaintRecord> paints)
    {
        var index = new Dictionary<string, string?>(StringComparer.Ordinal);
        foreach (PaintRecord paint in paints)
        {
            string brandSlug = paint.Id.Split('/')[0];
            string key = $"{brandSlug}|{paint.Name}|{paint.Range ?? ""}|{paint.ProductCode ?? ""}";
            index[key] = index.ContainsKey(key) ? null : paint.Id;
        }
        return index;
    }

    /// <summary>
    /// Holds a generated file to its own tallies. These files carry a <c>counts:</c> block written
    /// by the same run that wrote their bodies, so the two can only disagree if one was edited by
    /// hand -- which the files' own header forbids. Failing here turns a silent, partial relation
    /// into a build error naming the manufacturer.
    /// </summary>
    private static void VerifyCounts(
        string manufacturer, CanonicalSetCounts? counts, Dictionary<string, CanonicalSet> sets)
    {
        if (counts is null)
        {
            return;
        }

        int members = sets.Values.Sum(s => s.Members?.Count ?? 0);
        int unresolved = sets.Values.Sum(s => s.Unresolved?.Count ?? 0);
        int quantified = sets.Values.Sum(s => s.Members?.Count(m => m.Quantity.HasValue) ?? 0);

        Check("sets", counts.Sets, sets.Count);
        Check("members", counts.Members, members);
        Check("unresolved", counts.Unresolved, unresolved);
        Check("refs", counts.Refs, members + unresolved);
        Check("quantified", counts.Quantified, quantified);

        void Check(string name, int declared, int actual)
        {
            if (declared != actual)
            {
                throw new InvalidOperationException(
                    $"set-contents/{manufacturer}: counts.{name} says {declared} but the file holds {actual}");
            }
        }
    }
}
