using System.Linq;
using WarHub.PaintCatalog.Tool.Models;
using Xunit;

namespace WarHub.PaintCatalog.Tool.Tests.Models;

public class PaintRecordSchemaTests
{
    [Fact]
    public void PaintRecord_TopLevel_FieldOrder()
    {
        // `SoldSeparately` sits with `Status`/`Availability` because it is the same KIND of fact
        // -- how you can obtain this pot -- and property order here IS the on-disk key order, so a
        // reader meets the three together. It is deliberately not folded INTO either of them: both
        // are free strings every consumer filters on, and a new value there would silently exclude
        // the set-exclusive records the field exists to keep reachable.
        //
        // `Colourless` sits beside it for the same reason and reads as the same kind of fact --
        // what this product IS -- and, like SoldSeparately, is a sibling rather than a new value
        // inside an existing string field, so an unaware consumer is unaffected.
        string[] expected =
        [
            "Name", "Category", "Status", "Availability", "SoldSeparately", "Colourless", "FirstSeen",
            "ProductCode", "Ean", "AdditionalEans", "ImageUrl", "PriceGbp", "PriceUsd", "PriceEur",
            "PriceCad", "Supersedes", "SupersededBy", "Details",
        ];
        string[] actual = typeof(PaintRecord).GetProperties().Select(p => p.Name).ToArray();
        Assert.Equal(expected, actual);
    }

    [Fact]
    public void PaintDetails_FieldOrder()
    {
        // `WeightG` sits immediately after `VolumeMl` because the two are the same fact measured
        // two ways and the archive YAML should read that way; `container` follows both, as the
        // vessel the contents are in. Property order here IS the on-disk key order.
        string[] expected =
            ["Set", "R", "G", "B", "Hex", "VolumeMl", "WeightG", "Container", "Type", "Finish"];
        string[] actual = typeof(PaintDetails).GetProperties().Select(p => p.Name).ToArray();
        Assert.Equal(expected, actual);
    }

    /// <summary>
    /// `soldSeparately` is a TRI-STATE and the whole design rests on that: null means no source
    /// said, `false` means a source stated the pot is set-exclusive, and those are different
    /// claims. A non-nullable bool would read every silence as "not sold separately", turning
    /// 8,460 absences into assertions -- measured 2026-08-11: 8,461 committed records, of which
    /// exactly one states the field. So the nullability is a contract, not a style choice.
    /// </summary>
    [Fact]
    public void SoldSeparately_IsNullable_SoAbsenceStaysDistinctFromFalse()
    {
        System.Reflection.PropertyInfo property =
            typeof(PaintRecord).GetProperty("SoldSeparately")!;
        Assert.Equal(typeof(bool?), property.PropertyType);

        // And it defaults to null, so a record written without mentioning it asserts nothing.
        var record = new PaintRecord
        {
            Name = "x",
            Category = "paint",
            Status = "current",
            Availability = "unknown",
            Details = new PaintDetails { Set = "s", R = 0, G = 0, B = 0, Hex = "" },
        };
        Assert.Null(record.SoldSeparately);
    }
}
