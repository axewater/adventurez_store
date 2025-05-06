## API Specification: Submit Game Adventure

This document outlines how the Text Adventure Builder application can submit new adventures directly to the store via the API.

**Endpoint:** `/api/submit`

**Method:** `POST`

**Description:** Uploads a new text adventure package (ZIP file) along with required metadata. Submissions require moderator approval before appearing publicly.

**Authentication:**
Requires a valid API key provided in the request header.
*   **Header Name:** `X-API-Key`
*   **Value:** A valid, active API key obtained from the store's admin panel.

**Request Format:** `multipart/form-data`

**Request Body (Form Data):**

| Field             | Type   | Required | Description                                                                                                                                                              |
| :---------------- | :----- | :------- | :----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `adventure_file`  | File   | Yes      | The adventure package as a `.zip` file. **Must** contain a `game_data.json` file at its root level, which includes a `version` key indicating compatibility (e.g., "1.0"). Max file size: 50MB. |
| `name`            | String | Yes      | The name of the adventure as it should appear in the store.                                                                                                              |
| `description`     | String | Yes      | A description of the adventure.                                                                                                                                          |
| `tags`            | String | Yes      | A comma-separated string of **numeric IDs** for the tags associated with this adventure (e.g., `"1,5,8"`). These IDs correspond to existing tags in the store database. |

**Success Response (201 Created):**

*   **Content-Type:** `application/json`
*   **Body:** A JSON object indicating success and providing the ID assigned to the newly submitted adventure (which is pending approval).
    ```json
    {
      "message": "Adventure submitted successfully and is pending approval.",
      "adventure_id": 123
    }
    ```

**Error Responses:**

*   **400 Bad Request:** Indicates an issue with the submitted data.
    *   **Content-Type:** `application/json`
    *   **Body Examples:**
        ```json
        {"error": "Missing 'adventure_file' in request"}
        ```
        ```json
        {"error": "Only ZIP files are allowed"}
        ```
        ```json
        {"error": "Missing required metadata: name, description, tags"}
        ```
        ```json
        {"error": "Invalid format for 'tags'. Expected comma-separated IDs (e.g., '1,5,8')."}
        ```
        ```json
        {"error": "One or more provided tag IDs are invalid."}
        ```
        ```json
        {"error": "Missing 'game_data.json' inside the ZIP file."}
        ```
        ```json
        {"error": "Could not process ZIP file or game_data.json: [details]"}
        ```
*   **401 Unauthorized:** The `X-API-Key` header was missing.
    *   **Content-Type:** `application/json`
    *   **Body:**
        ```json
        {"error": "API key required"}
        ```
*   **403 Forbidden:** The provided API key was invalid or inactive.
    *   **Content-Type:** `application/json`
    *   **Body:**
        ```json
        {"error": "Invalid or inactive API key"}
        ```
*   **500 Internal Server Error:** A server-side error occurred (e.g., database issue).
    *   **Content-Type:** `application/json`
    *   **Body:**
        ```json
        {"error": "Database error during submission."} 
        ``` 
        *(Error message might vary slightly)*

**Important Notes:**

*   **Tag IDs:** The Text Adventure Builder will need a mechanism to know the valid `tag_id` values available in the store. This might involve a separate API endpoint to fetch available tags or pre-configuration within the builder.
*   **`game_data.json`:** The presence and basic validity (parsable JSON containing a `version` key) of `game_data.json` inside the ZIP are crucial for acceptance.
*   **Author:** The author of the submitted adventure is automatically determined based on the user associated with the provided API key.
*   **Moderation:** Successful submissions (201) are placed in a moderation queue