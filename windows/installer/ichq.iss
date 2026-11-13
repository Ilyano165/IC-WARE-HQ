; IC WARE HQ — Windows-Installer (Inno Setup 6, ADR-017). Installiert NUR den Launcher: Zugang zur zentralen
; Instanz der Firma. Keine Datenbank, kein Server, keine Firmendaten auf dem PC.
;
; Bauen (windows/build.ps1): iscc /DAppVersion=1.0.0rc1 /DQuelle=..\dist\ichq-launcher windows\installer\ichq.iss
; Stille Installation mit vorgegebener Adresse (z. B. Softwareverteilung):
;   IC-WARE-HQ-Setup-<version>.exe /VERYSILENT /SUPPRESSMSGBOXES /URL=https://hq.ihre-firma.de

#ifndef AppVersion
  #define AppVersion "0.0.0-dev"
#endif
#ifndef Quelle
  #define Quelle "..\..\dist\ichq-launcher"
#endif

[Setup]
AppId={{6A0E2C55-3F0B-4C8E-9C1E-1C9A6D2B7F41}
AppName=IC WARE HQ
AppVersion={#AppVersion}
AppVerName=IC WARE HQ {#AppVersion}
AppPublisher=IC Ware GbR
DefaultDirName={autopf}\IC WARE HQ
DefaultGroupName=IC WARE HQ
DisableProgramGroupPage=yes
; Ohne Administratorrechte für den eigenen Benutzer; Administratoren können „für alle" wählen
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
OutputDir=..\..\dist
OutputBaseFilename=IC-WARE-HQ-Setup-{#AppVersion}
SetupIconFile=ichq.ico
UninstallDisplayIcon={app}\ichq-launcher.exe
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

[Languages]
Name: "de"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "Verknüpfung auf dem Desktop anlegen"; GroupDescription: "Verknüpfungen:"

[Files]
Source: "{#Quelle}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\IC WARE HQ"; Filename: "{app}\ichq-launcher.exe"; Comment: "Zentrale IC-WARE-HQ-Instanz öffnen"
Name: "{group}\IC WARE HQ – Adresse ändern"; Filename: "{app}\ichq-launcher.exe"; Parameters: "--adresse-aendern"
Name: "{autodesktop}\IC WARE HQ"; Filename: "{app}\ichq-launcher.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\ichq-launcher.exe"; Description: "IC WARE HQ jetzt öffnen"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: files; Name: "{app}\server.json"

[Code]
var
  AdressSeite: TInputQueryWizardPage;

function VorhandeneAdresse(): String;
var
  Inhalt: AnsiString;
  P: Integer;
begin
  Result := '';
  if LoadStringFromFile(ExpandConstant('{app}\server.json'), Inhalt) then begin
    P := Pos('"url": "', Inhalt);
    if P > 0 then begin
      Result := Copy(Inhalt, P + 8, Length(Inhalt));
      Result := Copy(Result, 1, Pos('"', Result) - 1);
    end;
  end;
end;

procedure InitializeWizard();
begin
  AdressSeite := CreateInputQueryPage(wpSelectTasks, 'Adresse Ihrer Firma',
    'Unter welcher Adresse läuft IC WARE HQ für Ihre Firma?',
    'Die Adresse erhalten Sie von Ihrer Betreuung, z. B. hq.ihre-firma.de. Sie können das Feld leer lassen – ' +
    'dann fragt IC WARE HQ beim ersten Start danach.');
  AdressSeite.Add('Adresse (https://…):', False);
  AdressSeite.Values[0] := ExpandConstant('{param:URL|}');
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = AdressSeite.ID) and (AdressSeite.Values[0] = '') then
    AdressSeite.Values[0] := VorhandeneAdresse();
end;

function GueltigeZeichen(S: String): Boolean;
var
  I: Integer;
begin
  Result := True;
  for I := 1 to Length(S) do
    if Pos(S[I], 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-:/[]') = 0 then
      Result := False;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = AdressSeite.ID) and not GueltigeZeichen(Trim(AdressSeite.Values[0])) then begin
    MsgBox('Die Adresse enthält unerlaubte Zeichen. Beispiel: https://hq.ihre-firma.de', mbError, MB_OK);
    Result := False;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Adresse: String;
begin
  if CurStep = ssPostInstall then begin
    Adresse := Trim(AdressSeite.Values[0]);
    if Adresse = '' then
      Adresse := Trim(ExpandConstant('{param:URL|}'));
    { Nur geprüfte Zeichen landen in der JSON-Datei; die genaue Prüfung (https, ohne Pfad) macht der Launcher }
    if (Adresse <> '') and GueltigeZeichen(Adresse) then
      SaveStringToFile(ExpandConstant('{app}\server.json'), '{"url": "' + Adresse + '"}', False);
  end;
end;
