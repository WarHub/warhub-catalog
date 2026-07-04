using WarHub.PaintCatalog.Tool.Models;

namespace WarHub.PaintCatalog.Tool.Parsing;

/// <summary>
/// Parses Arcturus5404 markdown table files into Paint objects.
/// Handles both 6-column (Name|Set|R|G|B|Hex) and 7-column (Name|Code|Set|R|G|B|Hex) formats.
/// </summary>
public static class MarkdownPaintParser
{
    /// <summary>
    /// Parses a markdown file content into a list of paints.
    /// </summary>
    public static IReadOnlyList<Paint> Parse(string content)
    {
        var paints = new List<Paint>();
        string[] lines = content.Split('\n');

        bool? hasCodeColumn = null;
        bool headerSeen = false;

        foreach (string rawLine in lines)
        {
            string line = rawLine.Trim('\r', ' ');

            // Skip empty lines
            if (string.IsNullOrWhiteSpace(line))
                continue;

            // Must start with | to be a table row
            if (!line.StartsWith('|'))
                continue;

            string[] cells = SplitTableRow(line);

            // Detect header row
            if (!headerSeen && IsHeaderRow(cells))
            {
                hasCodeColumn = cells.Length >= 7 &&
                    cells[1].Equals("Code", StringComparison.OrdinalIgnoreCase);
                headerSeen = true;
                continue;
            }

            // Skip separator row (|---|---|...)
            if (IsSeparatorRow(cells))
                continue;

            if (!headerSeen || hasCodeColumn is null)
                continue;

            Paint? paint = ParseRow(cells, hasCodeColumn.Value);
            if (paint is not null)
            {
                paints.Add(paint);
            }
        }

        return paints;
    }

    private static string[] SplitTableRow(string line)
    {
        // Remove leading/trailing pipe and split
        string trimmed = line.Trim('|');
        return trimmed.Split('|');
    }

    private static bool IsHeaderRow(string[] cells)
    {
        // Header row contains "Name" in first cell and "Hex" in last cell
        if (cells.Length < 6) return false;
        return cells[0].Trim().Equals("Name", StringComparison.OrdinalIgnoreCase) &&
               cells[^1].Trim().Contains("Hex", StringComparison.OrdinalIgnoreCase);
    }

    private static bool IsSeparatorRow(string[] cells)
    {
        // Separator rows contain only dashes and spaces
        return cells.All(c => c.Trim().All(ch => ch == '-' || ch == ':'));
    }

    private static Paint? ParseRow(string[] cells, bool hasCodeColumn)
    {
        try
        {
            if (hasCodeColumn && cells.Length < 7) return null;
            if (!hasCodeColumn && cells.Length < 6) return null;

            int offset = hasCodeColumn ? 1 : 0;

            string name = cells[0].Trim();
            string? code = hasCodeColumn ? NormalizeCode(cells[1].Trim()) : null;
            string set = cells[1 + offset].Trim();
            string rStr = cells[2 + offset].Trim();
            string gStr = cells[3 + offset].Trim();
            string bStr = cells[4 + offset].Trim();
            string hexRaw = cells[5 + offset].Trim();

            if (!int.TryParse(rStr, out int r) ||
                !int.TryParse(gStr, out int g) ||
                !int.TryParse(bStr, out int b))
            {
                return null;
            }

            string? hex = HexExtractor.Extract(hexRaw);
            if (hex is null) return null;

            bool isDiscontinued = set.Contains("(discontinued)", StringComparison.OrdinalIgnoreCase)
                               || set.Contains("discontinued", StringComparison.OrdinalIgnoreCase);

            return new Paint
            {
                Name = name,
                ProductCode = code,
                Set = set,
                R = r,
                G = g,
                B = b,
                Hex = hex,
                IsDiscontinued = isDiscontinued
            };
        }
        catch
        {
            return null;
        }
    }

    private static string? NormalizeCode(string code)
    {
        if (string.IsNullOrWhiteSpace(code) ||
            code.Equals("null", StringComparison.OrdinalIgnoreCase))
        {
            return null;
        }
        return code;
    }
}
