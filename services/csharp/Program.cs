using System.Text.Json;
using System.Text.RegularExpressions;
using Microsoft.AspNetCore.Server.Kestrel.Core;
var builder = WebApplication.CreateBuilder(args);
builder.Logging.ClearProviders();
builder.WebHost.ConfigureKestrel(options => options.ListenAnyIP(int.Parse(Environment.GetEnvironmentVariable("PORT") ?? "8080"), listen => listen.Protocols = HttpProtocols.Http1));
var app = builder.Build();
var handler = new SocketsHttpHandler {AllowAutoRedirect = false, AutomaticDecompression = System.Net.DecompressionMethods.None, UseProxy = false};
var client = new HttpClient(handler) {Timeout = TimeSpan.FromMilliseconds(1500), DefaultRequestVersion = new Version(1,1), DefaultVersionPolicy = HttpVersionPolicy.RequestVersionExact};
static bool Integer(JsonElement v, double lo, double hi) => v.ValueKind == JsonValueKind.Number && v.TryGetDouble(out var n) && n >= lo && n <= hi && Math.Truncate(n) == n;
static Task Json(HttpContext c, int status, object value) {c.Response.StatusCode = status;return c.Response.WriteAsJsonAsync(value);}
static Task Error(HttpContext c, int status, string text) => Json(c, status, new {error = text});
app.Run(async context => {
    var raw = context.Features.Get<Microsoft.AspNetCore.Http.Features.IHttpRequestFeature>()!.RawTarget;
    var path = raw.Split('?')[0];
    var methods = new Dictionary<string,string>{{"/health","GET"},{"/io","GET"},{"/json","POST"},{"/cpu","POST"}};
    if (!methods.TryGetValue(path, out var method)) {await Error(context,404,"not_found");return;}
    if (context.Request.Method != method) {await Error(context,405,"method_not_allowed");return;}
    if (context.Request.QueryString.HasValue && context.Request.QueryString.Value != "?") {await Error(context,400,"invalid_request");return;}
    if (path == "/health") {await Json(context,200,new {status="ok"});return;}
    if (path == "/io") {
        try {
            using var request = new HttpRequestMessage(HttpMethod.Get, Environment.GetEnvironmentVariable("DOWNSTREAM_URL"));
            request.Headers.Add("Accept-Encoding","identity");
            // Non-replayable content prevents SocketsHttpHandler from resending a GET after a stale connection.
            request.Content = new OneShotContent();
            using var response = await client.SendAsync(request);
            var data = await response.Content.ReadAsByteArrayAsync();
            if ((int)response.StatusCode != 200 || data.Length != 1024 || data.Any(b => b != (byte)'x')) throw new Exception();
            context.Response.ContentType="application/octet-stream";await context.Response.Body.WriteAsync(data);
        } catch {await Error(context,502,"downstream_error");}
        return;
    }
    if (!string.Equals(context.Request.ContentType?.Split(';')[0].Trim(),"application/json",StringComparison.OrdinalIgnoreCase)) {await Error(context,415,"unsupported_media_type");return;}
    var bytes = new byte[4097];var count = 0;
    while (count < bytes.Length) {var n = await context.Request.Body.ReadAsync(bytes.AsMemory(count));if (n == 0) break;count += n;}
    if (count > 4096) {await Error(context,413,"payload_too_large");return;}
    try {
        using var doc = JsonDocument.Parse(bytes.AsMemory(0,count));
        var data = doc.RootElement;
        if (data.ValueKind != JsonValueKind.Object) throw new Exception();
        var keys = data.EnumerateObject().Select(p => p.Name).ToHashSet();
        if (path == "/cpu") {
            if (!keys.SetEquals(new[]{"seed"}) || !Integer(data.GetProperty("seed"),0,4294967295)) throw new Exception();
            var x=(uint)data.GetProperty("seed").GetDouble();
            for (var i=0;i<100000;i++) x=unchecked(1664525*x+1013904223);
            await Json(context,200,new {result=x});return;
        }
        if (!keys.SetEquals(new[]{"id","name","values","padding"}) || !Integer(data.GetProperty("id"),0,4294967295)) throw new Exception();
        var name=data.GetProperty("name").GetString();var padding=data.GetProperty("padding").GetString();var values=data.GetProperty("values");
        if (name is null || !Regex.IsMatch(name,"\\A[A-Za-z0-9_]{1,32}\\z") || padding != new string('x',896) || values.ValueKind != JsonValueKind.Array || values.GetArrayLength()!=16) throw new Exception();
        var sum=0;foreach (var v in values.EnumerateArray()) {if (!Integer(v,-1000,1000)) throw new Exception();sum+=(int)v.GetDouble();}
        await Json(context,200,new {id=(long)data.GetProperty("id").GetDouble(),name,sum,padding});
    } catch {await Error(context,400,"invalid_request");}
});
app.Run();
sealed class OneShotContent : HttpContent {
    private bool sent;
    protected override bool TryComputeLength(out long length) {length=0;return false;}
    protected override Task SerializeToStreamAsync(Stream stream, System.Net.TransportContext? context) {
        if (sent) throw new InvalidOperationException("Retries disabled");sent=true;return Task.CompletedTask;
    }
}
