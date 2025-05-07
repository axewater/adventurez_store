# Adventure Store API Documentatie

Dit document beschrijft de API-endpoints die beschikbaar zijn voor de Adventure Store, waarmee externe applicaties zoals de TextAdventureBuilder kunnen interageren.

## Authenticatie

Alle API-verzoeken vereisen een geldige API-sleutel die meegestuurd moet worden in de `X-API-Key` header.

`X-API-Key: uw_api_sleutel_hier`

Ongeldige of ontbrekende API-sleutels resulteren in een `401 Unauthorized` of `403 Forbidden` antwoord.

## Endpoints

### 1. Avontuur Indienen

*   **Endpoint:** `/api/submit`
*   **Methode:** `POST`
*   **Content-Type:** `multipart/form-data`
*   **Beschrijving:** Dient een nieuw avontuur in bij de store. Het avontuur wordt in een wachtrij geplaatst voor moderatie.
*   **Headers:**
    *   `X-API-Key`: Vereist.
*   **Formulier Data:**
    *   `adventure_file`: (Bestand) Vereist. Het ZIP-bestand van het avontuur. Dit ZIP-bestand *moet* een `game_data.json` bevatten met daarin minimaal `game_info.version` (versie van het avontuur zelf) en `game_info.builder_version` (versie van de TextAdventureBuilder waarmee het compatibel is). De `game_info.name` uit dit bestand wordt gebruikt als de naam van het avontuur. Een `game_info.description` kan ook worden meegegeven en zal gebruikt worden indien het `description` formulierveld leeg is.
    *   `name`: (String) Vereist. De naam van het avontuur.
    *   `description`: (String) Optioneel. Een beschrijving van het avontuur. Indien leeg, wordt de beschrijving uit `game_data.json` gebruikt, indien aanwezig.
    *   `tags`: (String) Vereist. Een komma-gescheiden lijst van tag ID's (bijv. "1,5,8"). Gebruik het `/api/tags` endpoint om beschikbare tags en hun ID's op te halen.
*   **Succes Antwoord (201 Created):**
    ```json
    {
        "message": "Adventure submitted successfully and is pending approval.",
        "adventure_id": 123
    }
    ```
*   **Fout Antwoorden:**
    *   `400 Bad Request`: Ongeldig bestandsformaat, bestandsgrootte overschreden, ongeldige tags, ontbrekende `game_data.json` in ZIP.
        ```json
        {"error": "Only ZIP files are allowed."}
        ```
        ```json
        {"error": "File size (XMB) exceeds the maximum allowed size (YMB)."}
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
        {"error": "Could not process ZIP file or game_data.json: <details>"}
        ```
        ```json
        {"error": "Adventure 'name' not found in 'game_data.json'."}
        ```
        ```json
        {"error": "Adventure name '<name>' is already in use by another author."} (HTTP 403)
        ```
        ```json
        {"error": "New version (<new_version>) must be higher than the current active version (<current_version>)."}
        ```
    *   `500 Internal Server Error`: Databasefout of onverwachte serverfout.
        ```json
        {"error": "Database error during submission."}
        ```
*   **Voorbeeld `curl` request:**
    ```bash
    curl -X POST "http://localhost:15000/api/submit" \
         -H "X-API-Key: uw_api_sleutel_hier" \
         -F "adventure_file=@/pad/naar/uw/avontuur.zip" \
         -F "description=Een episch verhaal vol mysterie." \
         -F "tags=1,3"
    ```

### 2. Beschikbare Tags Ophalen

*   **Endpoint:** `/api/tags`
*   **Methode:** `GET`
*   **Beschrijving:** Haalt een lijst op van alle beschikbare tags met hun ID's en namen.
*   **Headers:**
    *   `X-API-Key`: Vereist.
*   **Succes Antwoord (200 OK):**
    ```json
    [
        {"id": 1, "name": "Fantasy"},
        {"id": 2, "name": "Sci-Fi"},
        {"id": 3, "name": "Horror"}
    ]
    ```
*   **Fout Antwoorden:**
    *   `500 Internal Server Error`: Databasefout.
        ```json
        {"error": "Database error fetching tags."}
        ```
*   **Voorbeeld `curl` request:**
    ```bash
    curl -X GET "http://localhost:15000/api/tags" \
         -H "X-API-Key: uw_api_sleutel_hier"
    ```

### 3. Beschikbaarheid Titel Controleren

*   **Endpoint:** `/api/check_title_availability`
*   **Methode:** `GET`
*   **Beschrijving:** Controleert of een opgegeven avontuurtitel al in gebruik is. De controle is niet hoofdlettergevoelig.
*   **Headers:**
    *   `X-API-Key`: Vereist.
*   **Query Parameters:**
    *   `title`: (String) Vereist. De titel die gecontroleerd moet worden.
*   **Succes Antwoord (200 OK):**
    *   Indien titel beschikbaar:
        ```json
        {
            "status": "Available",
            "message": "This title can be used."
        }
        ```
    *   Indien titel niet beschikbaar:
        ```json
        {
            "status": "Not Available", // Kan ook zijn "This title is in use by another author." of "This title is already in use or pending."
            "message": "This title is already in use."
        }
        ```
*   **Fout Antwoorden:**
    *   `400 Bad Request`: `title` query parameter ontbreekt.
        ```json
        {"error": "Missing 'title' query parameter."}
        ```
    *   `500 Internal Server Error`: Databasefout of onverwachte serverfout.
        ```json
        {"error": "Database error during title check."}
        ```
*   **Voorbeeld `curl` request:**
    ```bash
    curl -X GET "http://localhost:15000/api/check_title_availability?title=Het Verlaten Kasteel" \
         -H "X-API-Key: uw_api_sleutel_hier"
    ```

## Algemene Foutcodes

*   `401 Unauthorized`: API-sleutel ontbreekt.
*   `403 Forbidden`: API-sleutel is ongeldig of inactief.
*   `500 Internal Server Error`: Er is een onverwachte fout opgetreden aan de serverkant.
