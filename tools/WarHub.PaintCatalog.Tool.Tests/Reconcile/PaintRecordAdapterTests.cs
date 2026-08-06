using WarHub.PaintCatalog.Tool.Models;
using WarHub.PaintCatalog.Tool.Reconcile;
using Xunit;

namespace WarHub.PaintCatalog.Tool.Tests.Reconcile;

public class PaintRecordAdapterTests
{
    private static PaintRecord R(string name = "Black", string set = "Base", string? code = "C1",
        string hex = "#000000", string status = "current", string availability = "unknown",
        int? vol = 12, string? finish = "Matte", string? ean = null, string? firstSeen = "2026-01-01") => new()
    {
        Name = name, Category = "paint", Status = status, Availability = availability,
        FirstSeen = firstSeen, ProductCode = code, Ean = ean, ImageUrl = null,
        Details = new PaintDetails { Set = set, R = 0, G = 0, B = 0, Hex = hex, VolumeMl = vol, Container = "pot", Type = "Base", Finish = finish },
    };

    private readonly PaintRecordAdapter _a = new();

    [Fact]
    public void IdentityKey_CombinesSetNameCodeHex_Normalized()
        => Assert.Equal("base|black|c1|#000000", _a.IdentityKey(R(name: "  Black ", set: "Base", code: "C1", hex: "#000000")));

    [Fact]
    public void IdentityKey_DistinguishesSameNameDifferentHex()
        => Assert.NotEqual(_a.IdentityKey(R(hex: "#010101", code: "A")), _a.IdentityKey(R(hex: "#000000", code: "B")));

    [Fact]
    public void Url_IsNull() => Assert.Null(_a.Url(R()));

    [Fact]
    public void Merge_UpdatesPresent_KeepsOnEmpty()
    {
        PaintRecord existing = R(ean: "111", vol: 12, finish: "Matte");
        PaintRecord fresh = R(ean: null, vol: 18, finish: null); // empty ean/finish kept; vol updated
        PaintRecord merged = _a.Merge(existing, fresh);
        Assert.Equal("111", merged.Ean);
        Assert.Equal(18, merged.Details.VolumeMl);
        Assert.Equal("Matte", merged.Details.Finish);
        Assert.Equal("2026-01-01", merged.FirstSeen); // immutable
    }

    [Fact]
    public void Merge_RebarcodingKeepsTheDisplacedBarcode()
    {
        // EAN is not part of the identity key, so a fresh harvest carrying a DIFFERENT barcode
        // lands on this same record and takes the primary slot. The barcode it displaced must be
        // retained -- a pot bought years ago has to stay resolvable by the barcode printed on it.
        PaintRecord merged = _a.Merge(R(ean: "5011921172221"), R(ean: "5011921175291"));
        Assert.Equal("5011921175291", merged.Ean);
        Assert.Equal(["5011921172221"], merged.AdditionalEans);
    }

    [Fact]
    public void Merge_UnchangedBarcodeAddsNoExtras()
    {
        // The single-barcode majority must stay byte-identical: null, never an empty list.
        PaintRecord merged = _a.Merge(R(ean: "5011921172221"), R(ean: "5011921172221"));
        Assert.Equal("5011921172221", merged.Ean);
        Assert.Null(merged.AdditionalEans);
    }

    [Fact]
    public void Merge_Status_StickyDiscontinued_AgainstFreshCurrent()
    {
        PaintRecord merged = _a.Merge(R(status: "discontinued"), R(status: "current"));
        Assert.Equal("discontinued", merged.Status);
    }

    [Fact]
    public void Merge_Status_FreshDiscontinuedWins()
    {
        PaintRecord merged = _a.Merge(R(status: "current"), R(status: "discontinued"));
        Assert.Equal("discontinued", merged.Status);
    }

    [Fact]
    public void WithFirstSeen_StampsOnlyWhenAbsent()
    {
        Assert.False(_a.HasFirstSeen(R(firstSeen: null)));
        Assert.Equal("2026-07-07", _a.WithFirstSeen(R(firstSeen: null), "2026-07-07").FirstSeen);
        Assert.True(_a.HasFirstSeen(R(firstSeen: "2026-01-01")));
    }

    [Fact]
    public void ApplyRename_AdoptsFreshIdentityFields_KeepsHistory()
    {
        // Colour-backfill alias: an archived colour-less record renamed onto its
        // hex-carrying fresh twin must ADOPT the fresh identity fields (else the stored
        // record disagrees with the key it sits under and the alias must fire forever),
        // while history (FirstSeen) and backfills (Ean) come from the archive side.
        PaintRecord existing = R(hex: "", ean: "111", firstSeen: "2026-07-23");
        PaintRecord fresh = R(hex: "#8A8D91", ean: null, firstSeen: null);
        PaintRecord renamed = _a.ApplyRename(existing, fresh);

        Assert.Equal("#8A8D91", renamed.Details.Hex);
        Assert.Equal("111", renamed.Ean);
        Assert.Equal("2026-07-23", renamed.FirstSeen);
        Assert.Equal(_a.IdentityKey(fresh), _a.IdentityKey(renamed)); // record matches its new key
    }

    [Fact]
    public void Merge_KeepsLastKnownPrice_WhenFreshQuotesNone()
    {
        // Price is evidence: a run whose bridge simply did not quote a figure must not blank the
        // record, but a fresh figure wins.
        PaintRecord existing = R() with { PriceGbp = 2.75m, PriceUsd = 4.50m };
        PaintRecord fresh = R() with { PriceGbp = 3.30m };
        PaintRecord merged = _a.Merge(existing, fresh);

        Assert.Equal(3.30m, merged.PriceGbp);
        Assert.Equal(4.50m, merged.PriceUsd);
    }

    [Fact]
    public void Merge_LineageIsDeclarative_FreshWinsIncludingWithdrawal()
    {
        // Unlike evidence fields, lineage comes from overrides.yaml. Withdrawing the declaration
        // has to actually withdraw the link, or a mistaken supersession is unfixable.
        PaintRecord existing = R() with { SupersededBy = "Black|Contrast", Supersedes = ["Old|Base"] };
        PaintRecord declared = _a.Merge(existing, R() with { SupersededBy = "Black|Speedpaint" });
        PaintRecord withdrawn = _a.Merge(existing, R());

        Assert.Equal("Black|Speedpaint", declared.SupersededBy);
        Assert.Null(declared.Supersedes);
        Assert.Null(withdrawn.SupersededBy);
        Assert.Null(withdrawn.Supersedes);
    }

    [Fact]
    public void ApplyRename_PureNameRename_OnlyChangesName()
    {
        PaintRecord existing = R(name: "Old Name", firstSeen: "2026-01-01");
        PaintRecord fresh = R(name: "New Name", firstSeen: null);
        PaintRecord renamed = _a.ApplyRename(existing, fresh);
        Assert.Equal("New Name", renamed.Name);
        Assert.Equal("2026-01-01", renamed.FirstSeen);
        Assert.Equal(_a.IdentityKey(fresh), _a.IdentityKey(renamed));
    }

    [Fact]
    public void Merge_AFreshWeightRetiresTheVolumeAlreadyCommittedToTheArchive()
    {
        // The last of the three `??` merges that had to fall for the weight change to be visible.
        // Fixing OverrideApplier alone is not enough: the two Green Stuff World tubs already have
        // `volumeMl: 17, container: dropper` ON DISK, and this method used to be
        // `fresh.Details.VolumeMl ?? existing.Details.VolumeMl` with a blank-aware `Pick` on the
        // container -- so the archive would have re-supplied both, forever, over a fresh record
        // that correctly stated neither.
        PaintRecord existing = R(vol: 17);
        PaintRecord fresh = R(vol: null) with
        {
            Details = R().Details with { VolumeMl = null, WeightG = 250, Container = null },
        };

        PaintRecord merged = _a.Merge(existing, fresh);

        Assert.Equal(250, merged.Details.WeightG);
        Assert.Null(merged.Details.VolumeMl);
        Assert.Null(merged.Details.Container);
    }

    [Fact]
    public void Merge_WithNoWeightOnEitherSideIsUnchangedFromTheOldCoalesce()
    {
        // The 8,545 records that are genuinely volume-sold: fresh volume wins, a fresh record
        // silent on volume keeps the stored one, and a blank container still falls back.
        Assert.Equal(18, _a.Merge(R(vol: 12), R(vol: 18)).Details.VolumeMl);
        Assert.Equal(12, _a.Merge(R(vol: 12), R(vol: null)).Details.VolumeMl);
        Assert.Equal("pot", _a.Merge(R(vol: 12), R(vol: 18)).Details.Container);
        Assert.Null(_a.Merge(R(vol: 12), R(vol: 18)).Details.WeightG);
    }
}
