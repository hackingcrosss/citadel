# Email Message-Level Signals: Best Practices

Use this reference when composing, reviewing, or advising on email messages to optimize deliverability and avoid spam classification by Microsoft Exchange (BCL) and other filtering engines.

## Content

### Do

- Use plain, clear language. Write like a human, not a marketing template.
- Maintain a balanced text-to-image ratio. Text-heavy is safer than image-heavy.
- Include a visible, functional unsubscribe link.
- Include an RFC 8058 `List-Unsubscribe` header.
- Keep HTML clean and minimal. Use inline CSS. Avoid unnecessary nested tables.

### Don't

- Use ALL CAPS, excessive punctuation (e.g., `!!!`), or spammy phrases ("Act now", "Free", "Limited time").
- Send image-only emails with no text. Filters cannot read images and will assume the worst.
- Use URL shorteners (e.g., bit.ly). They are associated with link obfuscation.
- Include too many links, especially to different domains.
- Embed JavaScript or form elements in HTML emails.
- Attach large files. Link to hosted files instead.

## Structure

### Do

- Use a consistent `From` name and address across campaigns.
- Ensure the `From` domain and `Return-Path` domain match (SPF/DMARC alignment).
- Set the `List-Unsubscribe-Post: List-Unsubscribe=One-Click` header.
- Use a `Reply-To` address that is monitored and accepts replies.
- Send MIME multipart messages: include both an HTML and a plain text part.

### Don't

- Change sender identity frequently.
- Use a `noreply@` address. It discourages engagement and prevents replies.
- Send without proper `Message-ID` and `Date` headers.

## Tracking and Technical

### Do

- Use your own domain (CNAME) for tracking links and pixels, not your ESP's default shared domain.
- Ensure all links use HTTPS.
- Verify that all linked domains have clean reputation.

### Don't

- Embed tracking pixels from multiple third-party domains.
- Link to newly registered or low-reputation domains.
- Use redirects through multiple domains before reaching the final landing page.

## Key Principle

If your content consistently generates engagement (opens, replies, moves to inbox), message-level signals become less critical. Content quality and recipient relevance outweigh technical formatting.
