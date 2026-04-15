# Troubleshooting Alexa Request Delivery

This is a step-by-step guide for diagnosing issues when Alexa
does not trigger the EchoWeave Cloudflare Worker.

## Golden Rule: Test in the Simulator First

Before testing on a physical Echo device, **always** verify the connection using the Alexa Developer Console Simulator. The Simulator removes device-specific variables (like Amazon household profiles, wrong accounts, or mismatched device languages).

### Phase 1: Simulator Testing & Endpoint Config

1. Go to the [Alexa Developer Console](https://developer.amazon.com/alexa/console/ask) and open your skill.
2. Go to the **Build** tab -> **Invocation**.
   - Change the **Skill Invocation Name** to something unique, like `echo weave bridge`. (Using generic names like "hello world" can cause conflicts with Amazon's own test skills or other sample skills on your account).
3. Click **Save Model**, then click **Build Model**. Wait for "Build Successful".
4. Go to **Endpoint**.
   - Ensure the HTTPS URL is exactly: `https://echoweave-edge-worker.echoweave-staging-20260328.workers.dev/v1/alexa`
   - SSL certificate type: "My development endpoint has a certificate from a trusted certificate authority"
5. Open the **Cloudflare Dashboard** -> `echoweave-edge-worker` -> **Logs** -> **Real-time** -> **Begin log stream**.
6. Go back to Alexa Developer Console -> **Test** tab.
   - Set "Skill testing is enabled in:" to **Development**.
   - In the Simulator input box, type: `open echo weave bridge` (or whatever unique name you chose) and hit Enter.

### Phase 1 Decision Tree:
- **No Cloudflare Event?** The request is failing at Amazon's firewall or Cloudflare's WAF. 
  - Check Cloudflare Security Events for blocks (Bot Fight Mode might be blocking Amazon).
  - Triple-check the Endpoint URL for typos or missing `/v1/alexa`.
- **Cloudflare Event Received (`worker_request_received`)?** Your endpoint, certificates, and WAF are perfect. Move to Phase 2.

---

### Phase 2: Physical Echo Device Testing

If the Simulator works but your real Echo device does not, the issue is locked to the physical device's context.

**Verify these device settings:**
1. **Amazon Account Match:** The Echo device is logged into the **same Amazon account** as your Developer Console.
   - *Check:* Alexa app → Settings → Account.
   - *Fix:* Switch profiles by saying "Alexa, switch profiles" if you are in an Amazon Household.
2. **Device Locale:** The Echo device language must match the skill locale.
   - *Check:* Alexa app → Devices → Echo device → Language. It must be **English (United States)** for `en-US`.
3. **The Voice Command:**
   - Say: `"Alexa, open echo weave bridge"`
   - Wait for the welcome message.
   - Say: `"play"`

### Phase 2 Decision Tree:
- **No Cloudflare Event?** It's a device context issue (Account mismatch, Locale mismatch, or the microphone misheard the invocation name).
- **Worker Event Appears?** Request delivery is solved! You can now proceed to debug D1, Durable Objects, and Connectors.

## UI-Initiated Playback Limitation

If playback is started from the Music Assistant UI (which triggers `/ma/push-url`) and logs show:

- `inbound_request_id: ""`
- `last_alexa_probe.probe_id: ""`
- `last_alexa_probe.probe_time: ""`
- `alexa_request_context_missing`
- `prototype_skill_response_skipped_no_active_request`

then EchoWeave is correctly enforcing Alexa session rules. In this case, `/ma/push-url` returns `ui_play_requires_active_alexa_skill_session` because prototype-skill `AudioPlayer.Play` can only be attached to a live Alexa request/response cycle.

Current behavior in this path:

- No worker handoff/prototype response attempt.
- No fake playback-start success state for Echo devices.
- User must first create an active Alexa skill session (for example by invoking the skill by voice).

## Log Event Reference

| Event Name | When | Indicates |
|---|---|---|
| `worker_request_received` | Every request | Request reached Worker |
| `alexa_request_routed` | POST /v1/alexa | Routed to Alexa handler |
| `alexa_signature_result` | After sig check | Signature pass/fail |
| `alexa_envelope_parsed` | After parsing | Request type + intent |

