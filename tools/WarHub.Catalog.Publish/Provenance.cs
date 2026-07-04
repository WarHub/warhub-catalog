namespace WarHub.Catalog.Publish;

/// <summary>
/// Everything the publisher needs to stamp provenance onto artifacts — all injected
/// up front (the workflow computes the version/tag before bundling), so a build is
/// fully deterministic and no file is rewritten after the release is cut.
/// </summary>
internal sealed class Provenance
{
    public required string Version { get; init; }
    public required string GeneratedAt { get; init; }
    public string? GitCommit { get; init; }
    public required string Repo { get; init; }
    public ReleaseRef? Release { get; init; }

    /// <summary>Base Pages URL, no trailing slash, e.g. https://warhub.github.io/warhub-catalog.</summary>
    public string? PageBaseUrl { get; init; }

    /// <summary>Per-document source block, with the file's own Pages URL.</summary>
    public SourceRef SourceFor(string relPath) => new(
        Repo,
        Release,
        PageBaseUrl is null ? null : $"{PageBaseUrl}/{relPath}");
}
