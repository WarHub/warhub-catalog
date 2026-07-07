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
            ["Name", "Category", "Status", "Availability", "FirstSeen", "ProductCode", "Ean", "ImageUrl", "Details"];
        string[] actual = typeof(PaintRecord).GetProperties().Select(p => p.Name).ToArray();
        Assert.Equal(expected, actual);
    }

    [Fact]
    public void PaintDetails_FieldOrder()
    {
        string[] expected =
            ["Set", "R", "G", "B", "Hex", "VolumeMl", "Container", "Type", "Finish"];
        string[] actual = typeof(PaintDetails).GetProperties().Select(p => p.Name).ToArray();
        Assert.Equal(expected, actual);
    }
}
