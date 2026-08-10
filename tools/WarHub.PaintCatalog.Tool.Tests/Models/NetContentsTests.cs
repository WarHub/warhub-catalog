using WarHub.PaintCatalog.Tool.Models;

namespace WarHub.PaintCatalog.Tool.Tests.Models;

/// <summary>
/// The one net-contents merge rule, shared by all four write sites (VolumeEnricher,
/// BarcodeEnricher, OverrideApplier, PaintRecordAdapter). Two things are being pinned: that a
/// weight assertion actually CLEARS the volume it displaces, and -- much more importantly -- that
/// on data carrying no weight at all the rule is byte-identical to the `incoming ?? current` /
/// `Pick` coalesces it replaced. The second is what makes the change safe for the 8,545 of 8,547
/// committed records (measured 2026-08-06) that are genuinely volume-sold.
/// </summary>
public class NetContentsTests
{
    private static NetContents.Claim C(int? ml = null, int? g = null, string? container = null) =>
        new(ml, g, container);

    [Fact]
    public void AWeightAssertionRetiresTheVolumeAndTheContainerItDisplaces()
    {
        // The exact shape of the two Green Stuff World foam-primer tubs: VolumeTable's brand-wide
        // row has already written 17/dropper into `current` by the time the override is read, so a
        // coalesce here would publish `weightG: 250` beside a still-wrong `volumeMl: 17`.
        NetContents.Claim merged = NetContents.Merge(C(g: 250), C(ml: 17, container: "dropper"));

        Assert.Null(merged.VolumeMl);
        Assert.Equal(250, merged.WeightG);
        Assert.Null(merged.Container);
    }

    [Fact]
    public void AWeightAssertionMayStillCarryItsOwnVolumeAndContainer()
    {
        // A pigment weighed into a jar of stated size states BOTH facts about one record. The
        // sibling shape is chosen precisely so that needs no discriminator; the clear only removes
        // what the asserting writer did not itself supply.
        NetContents.Claim merged =
            NetContents.Merge(C(ml: 30, g: 20, container: "jar"), C(ml: 17, container: "dropper"));

        Assert.Equal(30, merged.VolumeMl);
        Assert.Equal(20, merged.WeightG);
        Assert.Equal("jar", merged.Container);
    }

    [Fact]
    public void AVolumeAssertionRetiresAStoredMass()
    {
        // Symmetric, so withdrawing a weight assertion actually withdraws it rather than leaving a
        // record claiming both -- the discipline PaintRecordAdapter.cs:54-59 applies to lineage.
        NetContents.Claim merged = NetContents.Merge(C(ml: 17, container: "dropper"), C(g: 250));

        Assert.Equal(17, merged.VolumeMl);
        Assert.Null(merged.WeightG);
    }

    [Fact]
    public void AVolumeAssertionDoesNotClearTheContainerBesideIt()
    {
        // Routine on real data: a bridge row or a per-record override states a size and nothing
        // else, and must keep the container VolumeTable established. This is the asymmetry with
        // the weight case and the reason it is spelled out rather than folded into one branch.
        NetContents.Claim merged = NetContents.Merge(C(ml: 24), C(ml: 12, container: "pot"));

        Assert.Equal(24, merged.VolumeMl);
        Assert.Equal("pot", merged.Container);
    }

    [Theory]
    // (incoming ml, incoming container, current ml, current container)
    [InlineData(null, null, null, null)]
    [InlineData(12, "pot", null, null)]
    [InlineData(null, null, 12, "pot")]
    [InlineData(24, null, 12, "pot")]
    [InlineData(null, "spray", 400, "dropper")]
    [InlineData(18, "dropper", 18, "dropper")]
    [InlineData(null, "", 12, "pot")]
    public void WithNoWeightAnywhereItIsExactlyTheCoalesceItReplaced(
        int? incomingMl, string? incomingContainer, int? currentMl, string? currentContainer)
    {
        // THE COMPATIBILITY PROOF. Every one of the four sites previously did `incoming ?? current`
        // on the volume and a blank-aware `Pick` on the container. `weightG` is null on 8,545 of
        // 8,547 committed records and on every one of the 38 VolumeTable rules, so if this
        // reduction holds the contract change cannot move a single volume-sold record -- which is
        // the guarantee the archive diff is supposed to show, and the archive is not regenerated
        // by this commit.
        NetContents.Claim merged = NetContents.Merge(
            C(incomingMl, container: incomingContainer), C(currentMl, container: currentContainer));

        Assert.Equal(incomingMl ?? currentMl, merged.VolumeMl);
        Assert.Null(merged.WeightG);
        Assert.Equal(
            string.IsNullOrWhiteSpace(incomingContainer) ? currentContainer : incomingContainer,
            merged.Container);
    }

    [Fact]
    public void AWriterThatSaysNothingChangesNothing()
    {
        NetContents.Claim merged = NetContents.Merge(C(), C(ml: 30, g: 20, container: "jar"));

        Assert.Equal(30, merged.VolumeMl);
        Assert.Equal(20, merged.WeightG);
        Assert.Equal("jar", merged.Container);
    }

    [Fact]
    public void AMassStatedBesideAVolumeKeepsTheContainer()
    {
        // The pigment-in-a-jar case the field exists to allow: 20 g weighed into a known 30 ml
        // jar is TWO true facts, and the vessel is not in doubt. An earlier draft cleared the
        // container in the weight branch unconditionally, which would have stripped `jar` from
        // the 29 committed 30 ml/jar pigment records the moment any of them gained a mass.
        var current = new NetContents.Claim(VolumeMl: 30, WeightG: null, Container: "jar");
        var incoming = new NetContents.Claim(VolumeMl: 30, WeightG: 20, Container: null);

        var merged = NetContents.Merge(incoming, current);

        Assert.Equal(30, merged.VolumeMl);
        Assert.Equal(20, merged.WeightG);
        Assert.Equal("jar", merged.Container);
    }

    [Fact]
    public void AMassStatedAloneStillRetiresTheVolumeAndItsContainer()
    {
        // The other half, and why the branch cannot simply always keep the container: VolumeTable
        // writes volume and container as a PAIR, so when the volume is wrong the container beside
        // it was never observed either. Both Green Stuff World foam-primer tubs read
        // `17 ml`/`dropper` from one brand-wide row and are 250 g tubs.
        var current = new NetContents.Claim(VolumeMl: 17, WeightG: null, Container: "dropper");
        var incoming = new NetContents.Claim(VolumeMl: null, WeightG: 250, Container: null);

        var merged = NetContents.Merge(incoming, current);

        Assert.Null(merged.VolumeMl);
        Assert.Equal(250, merged.WeightG);
        Assert.Null(merged.Container);
    }
}
