export default {
  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);
    const requestId = request.headers.get("x-request-id") || Math.random().toString(36).substring(7);
    
    const headerNames: string[] = [];
    request.headers.forEach((_, key) => headerNames.push(key));

    console.info(JSON.stringify({
      event: "minimal_worker_request_received",
      method: request.method,
      path: url.pathname,
      request_id: requestId,
      headers: headerNames
    }));

    if (url.pathname === "/v1/alexa") {
      if (request.method === "GET") {
        return new Response("Minimal test worker reached successfully via GET.", { status: 200 });
      }

      if (request.method === "POST") {
        const responseBody = {
          version: "1.0",
          response: {
            outputSpeech: {
              type: "PlainText",
              text: "Minimal test worker reached successfully"
            },
            shouldEndSession: true
          }
        };

        return new Response(JSON.stringify(responseBody), {
          status: 200,
          headers: { "Content-Type": "application/json" }
        });
      }
    }

    return new Response("Not Found", { status: 404 });
  }
};
