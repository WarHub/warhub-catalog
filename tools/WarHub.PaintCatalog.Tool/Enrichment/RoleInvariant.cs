using WarHub.PaintCatalog.Tool.Models;

namespace WarHub.PaintCatalog.Tool.Enrichment;

/// <summary>
/// The one rule that ties <see cref="PaintRecord.Role"/> to <see cref="PaintRecord.Colourless"/>:
/// a varnish, medium or cleaner deposits no colour, so the record must say so, and a record that
/// says it has no colour cannot be a colour. Checked over every record the tool is about to
/// write -- fresh ones and archived ones a source no longer asserts alike -- and a violation FAILS
/// THE RUN before anything is written (maintainer decision, 2026-09-02): the archive is the
/// only place the two facts meet, and an archive that contradicts itself is worse than a run that
/// refused.
///
/// Why both directions. The forward one (role ⇒ flag) is what keeps a newly classified thinner
/// out of the colour-equivalence graph, which reads the flag and not the role
/// (<see cref="Equivalence.EquivalenceFinder"/>). The reverse one (flag ⇒ not colour) is what
/// catches a classifier rule that has gone quiet -- a varnish renamed upstream, say -- while the
/// hand flag still stands. Measured on the first run, 2026-09-02, against the 146 committed
/// flags: 6 violations, all forward, all records the classifier was right about and the archive
/// had never flagged (Vallejo's Xpress Medium and Wet Effects, Mr Hobby's Super Smooth Clear,
/// Tamiya's two Pearl Clears, AK's Oxidizing Agent); zero reverse.
///
/// A missing role is a violation too: the tool stamps every record it writes, so an absent one
/// means a code path skipped the classifier, not that a record may legitimately have none.
/// </summary>
public static class RoleInvariant
{
    /// <summary>One line per violating record, ready to print; empty when the brand is consistent.</summary>
    public static IReadOnlyList<string> Violations(string brandSlug, IEnumerable<PaintRecord> records)
    {
        var violations = new List<string>();
        foreach (PaintRecord r in records)
        {
            string where = $"{brandSlug}: '{r.Name}' [{r.Details.Set}]"
                + (string.IsNullOrEmpty(r.ProductCode) ? "" : $" {r.ProductCode}");

            if (string.IsNullOrWhiteSpace(r.Role))
            {
                violations.Add($"{where}: no role");
            }
            else if (!RoleClassifier.Vocabulary.Contains(r.Role))
            {
                violations.Add($"{where}: role '{r.Role}' is not in the vocabulary ({string.Join(", ", RoleClassifier.Roles)})");
            }
            else if (RoleClassifier.ColourlessRoles.Contains(r.Role) && r.Colourless != true)
            {
                violations.Add($"{where}: role {r.Role} requires `colourless: true` -- declare it in overrides.yaml "
                    + "(with a paired alias if the record carries a stand-in hex), or fix the rule that classified it");
            }
            else if (r.Colourless == true && r.Role == RoleClassifier.Colour)
            {
                violations.Add($"{where}: `colourless: true` but role colour -- give it a role in overrides.yaml, or withdraw the flag");
            }
        }

        return violations;
    }
}
