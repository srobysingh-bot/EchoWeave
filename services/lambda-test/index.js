exports.handler = async (event) => {
    console.log("Received event:", JSON.stringify(event, null, 2));
    
    const alexaResponse = {
        version: "1.0",
        response: {
            outputSpeech: {
                type: "PlainText",
                text: "Hello from Lambda isolation test. I successfully received your request."
            },
            shouldEndSession: true
        }
    };

    // If invoked via Function URL or API Gateway
    if (event.requestContext && event.requestContext.http) {
        return {
            statusCode: 200,
            body: JSON.stringify(alexaResponse),
            headers: {
                "Content-Type": "application/json"
            }
        };
    }
    
    // If invoked directly via Lambda ARN from Alexa Skill Developer Console
    return alexaResponse;
};
