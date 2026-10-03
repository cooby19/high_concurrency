import com.google.gson.*;
import com.sun.net.httpserver.*;
import java.net.*;
import java.net.http.*;
import java.nio.charset.*;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.*;

public class Main {
    static final Gson GSON = new Gson();
    static final HttpClient CLIENT = HttpClient.newBuilder().version(HttpClient.Version.HTTP_1_1)
        .followRedirects(HttpClient.Redirect.NEVER).connectTimeout(Duration.ofMillis(1500)).build();
    static boolean integer(JsonElement v, double lo, double hi) {
        if (v == null || !v.isJsonPrimitive() || !v.getAsJsonPrimitive().isNumber()) return false;
        double n = v.getAsDouble(); return n >= lo && n <= hi && n == Math.floor(n);
    }
    static void send(HttpExchange e, int code, Object data) throws Exception {
        byte[] b = GSON.toJson(data).getBytes(StandardCharsets.UTF_8);
        e.getResponseHeaders().set("Content-Type", "application/json"); e.sendResponseHeaders(code, b.length);
        e.getResponseBody().write(b);
    }
    static void fail(HttpExchange e, int code, String message) throws Exception {send(e, code, Map.of("error", message));}
    static void handle(HttpExchange e) throws Exception {
        String path = e.getRequestURI().getRawPath();
        String method = Map.of("/health","GET","/io","GET","/json","POST","/cpu","POST").get(path);
        if (method == null) {fail(e,404,"not_found"); return;}
        if (!e.getRequestMethod().equals(method)) {fail(e,405,"method_not_allowed"); return;}
        if (e.getRequestURI().getRawQuery() != null && !e.getRequestURI().getRawQuery().isEmpty()) {fail(e,400,"invalid_request");return;}
        if (path.equals("/health")) {send(e,200,Map.of("status","ok"));return;}
        if (path.equals("/io")) {
            try {
                var req = HttpRequest.newBuilder(URI.create(System.getenv("DOWNSTREAM_URL")))
                    .timeout(Duration.ofMillis(1500)).header("Accept-Encoding","identity").GET().build();
                // Future timeout includes receiving the full body, not only response headers.
                var response = CLIENT.sendAsync(req, HttpResponse.BodyHandlers.ofByteArray()).get(1500, TimeUnit.MILLISECONDS);
                if (response.statusCode() != 200 || !Arrays.equals(response.body(), "x".repeat(1024).getBytes(StandardCharsets.US_ASCII))) throw new Exception();
                e.getResponseHeaders().set("Content-Type","application/octet-stream");e.sendResponseHeaders(200,1024);e.getResponseBody().write(response.body());
            } catch (Exception ex) {fail(e,502,"downstream_error");}
            return;
        }
        String type = e.getRequestHeaders().getFirst("Content-Type");
        if (type == null || !type.split(";",2)[0].trim().equalsIgnoreCase("application/json")) {fail(e,415,"unsupported_media_type");return;}
        byte[] raw = e.getRequestBody().readNBytes(4097);
        if (raw.length > 4096) {fail(e,413,"payload_too_large");return;}
        JsonObject data;
        try {
            String text = StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT).decode(java.nio.ByteBuffer.wrap(raw)).toString();
            var reader = new com.google.gson.stream.JsonReader(new java.io.StringReader(text));
            reader.setStrictness(Strictness.STRICT);
            JsonElement parsed = GSON.fromJson(reader, JsonElement.class);
            if (reader.peek() != com.google.gson.stream.JsonToken.END_DOCUMENT || text.startsWith("\ufeff") || parsed == null || !parsed.isJsonObject()) throw new Exception();
            data = parsed.getAsJsonObject();
            if (path.equals("/cpu")) {
                if (!data.keySet().equals(Set.of("seed")) || !integer(data.get("seed"),0,4294967295d)) throw new Exception();
                int x = (int)data.get("seed").getAsDouble();
                // Convert via long so Java's saturating double->int conversion cannot corrupt uint32 seeds.
                x = (int)(long)data.get("seed").getAsDouble();
                for (int i=0;i<100000;i++) x = 1664525*x + 1013904223;
                send(e,200,Map.of("result",Integer.toUnsignedLong(x)));return;
            }
            if (!data.keySet().equals(Set.of("id","name","values","padding")) || !integer(data.get("id"),0,4294967295d)
                || !data.get("name").isJsonPrimitive() || !data.getAsJsonPrimitive("name").isString()
                || !data.get("name").getAsString().matches("[A-Za-z0-9_]{1,32}")
                || !data.get("padding").isJsonPrimitive() || !data.getAsJsonPrimitive("padding").isString()
                || !data.get("padding").getAsString().equals("x".repeat(896))
                || !data.get("values").isJsonArray() || data.getAsJsonArray("values").size()!=16) throw new Exception();
            int sum=0;for (JsonElement v:data.getAsJsonArray("values")) {if (!integer(v,-1000,1000)) throw new Exception();sum+=(int)v.getAsDouble();}
            send(e,200,Map.of("id",(long)data.get("id").getAsDouble(),"name",data.get("name").getAsString(),"sum",sum,"padding",data.get("padding").getAsString()));
        } catch (Exception ex) {fail(e,400,"invalid_request");}
    }
    public static void main(String[] args) throws Exception {
        var server=HttpServer.create(new InetSocketAddress("0.0.0.0",Integer.parseInt(System.getenv().getOrDefault("PORT","8080"))),1024);
        server.setExecutor(Executors.newVirtualThreadPerTaskExecutor());
        server.createContext("/",e->{try {handle(e);} catch(Exception ignored) {} finally {e.close();}});
        server.start();
    }
}
