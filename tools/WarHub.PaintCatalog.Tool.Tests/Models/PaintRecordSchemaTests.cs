using System.Linq;
using WarHub.PaintCatalog.Tool.Models;
using Xunit;

namespace WarHub.PaintCatalog.Tool.Tests.Models;

public class PaintRecordSchemaTests
{
    [Fact]
    public void PaintRecord_TopLevel_FieldOrder()
    {
        string[] expected =
        [
            "Name", "Category", "Status", "Availability", "FirstSeen", "ProductCode", "Ean",
            "AdditionalEans", "ImageUrl", "PriceGbp", "PriceUsd", "PriceEur", "PriceCad",
            "Supersedes", "SupersededBy", "Details",
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
}
