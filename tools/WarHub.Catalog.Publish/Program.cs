using System.CommandLine;
using WarHub.Catalog.Publish;

Option<DirectoryInfo> catalogDirOption = new("--catalog-dir")
{
    Description = "Source canonical catalog directory (contains products/*.yaml, taxonomy/*.yaml)",
    DefaultValueFactory = _ => new DirectoryInfo(Path.Combine("data", "catalog")),
};
Option<DirectoryInfo> paintsDirOption = new("--paints-dir")
{
    Description = "Source paint data directory (contains brands/*.yaml, equivalences.yaml)",
    DefaultValueFactory = _ => new DirectoryInfo(Path.Combine("data", "paints")),
};
Option<DirectoryInfo> outOption = new("--out")
{
    Description = "Output directory for the published JSON tree",
    DefaultValueFactory = _ => new DirectoryInfo("dist"),
};
Option<string> versionOption = new("--catalog-version")
{
    Description = "Catalog version (yyyy.m.d[.n]); defaults to today (UTC)",
    DefaultValueFactory = _ => $"{DateTime.UtcNow:yyyy}.{DateTime.UtcNow.Month}.{DateTime.UtcNow.Day}",
};
Option<string?> gitCommitOption = new("--git-commit") { Description = "Source git commit SHA" };
Option<string?> generatedAtOption = new("--generated-at") { Description = "ISO-8601 build timestamp (defaults to now, UTC)" };
Option<string> repoOption = new("--repo")
{
    Description = "owner/name of the catalog repo",
    DefaultValueFactory = _ => "WarHub/warhub-catalog",
};
Option<string?> releaseTagOption = new("--release-tag") { Description = "Release tag (e.g. v2026.7.4)" };
Option<string?> releaseUrlOption = new("--release-url") { Description = "Release URL (derived from repo+tag if omitted)" };
Option<string?> pageBaseUrlOption = new("--page-base-url") { Description = "Pages base URL, no trailing slash" };

RootCommand root = new("WarHub Catalog Publisher — bundles source YAML into the versioned JSON catalog")
{
    catalogDirOption, paintsDirOption, outOption, versionOption, gitCommitOption,
    generatedAtOption, repoOption, releaseTagOption, releaseUrlOption, pageBaseUrlOption,
};

root.SetAction(parseResult =>
{
    string catalogDir = parseResult.GetValue(catalogDirOption)!.FullName;
    string paintsDir = parseResult.GetValue(paintsDirOption)!.FullName;
    string outDir = parseResult.GetValue(outOption)!.FullName;
    string version = parseResult.GetValue(versionOption)!;
    string? gitCommit = parseResult.GetValue(gitCommitOption);
    string generatedAt = parseResult.GetValue(generatedAtOption)
        ?? DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ");
    string repo = parseResult.GetValue(repoOption)!;
    string? releaseTag = parseResult.GetValue(releaseTagOption);
    string? releaseUrl = parseResult.GetValue(releaseUrlOption);
    string? pageBaseUrl = parseResult.GetValue(pageBaseUrlOption)?.TrimEnd('/');

    ReleaseRef? release = releaseTag is { Length: > 0 }
        ? new ReleaseRef(releaseTag, releaseUrl ?? $"https://github.com/{repo}/releases/tag/{releaseTag}")
        : null;

    var prov = new Provenance
    {
        Version = version,
        GeneratedAt = generatedAt,
        GitCommit = gitCommit,
        Repo = repo,
        Release = release,
        PageBaseUrl = pageBaseUrl,
    };

    string schemaDir = Path.Combine(AppContext.BaseDirectory, "schema");
    PublishResult result = Publisher.Run(new PublishOptions(catalogDir, paintsDir, outDir, schemaDir, prov));

    Console.WriteLine($"Published catalog {version}: {result.Products} products, {result.Paints} paints, "
        + $"{result.Files} files → {outDir}");
    return 0;
});

return await root.Parse(args).InvokeAsync();
