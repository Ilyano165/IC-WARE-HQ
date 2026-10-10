; IC WARE HQ SERVER — Windows-Installer (Inno Setup 6, ADR-018). Macht diesen PC zum Server für alle Nutzer:
; eigene WSL2-Linux-Umgebung „IC-WARE-HQ" mit dem geprüften Linux-Stack, öffentlich erreichbar über einen
; Cloudflare-Tunnel (kein offener Port am Router). Daten bleiben bei Deinstallation, außer man wählt „löschen".
;
; Bauen: windows\build-server.ps1   Stille Installation (z. B. Test):
;   IC-WARE-HQ-Server-Setup-<v>.exe /VERYSILENT /DOMAIN=hq.firma.de /EMAIL=it@firma.de /TOKENFILE=C:\pfad\token.txt

#ifndef AppVersion
  #define AppVersion "0.0.0-dev"
#endif

[Setup]
AppId={{B3F1C2D4-7E8A-4B5C-9D0E-1F2A3B4C5D6E}
AppName=IC WARE HQ Server
AppVersion={#AppVersion}
AppVerName=IC WARE HQ Server {#AppVersion}
AppPublisher=IC Ware GbR
DefaultDirName={autopf}\IC WARE HQ Server
DefaultGroupName=IC WARE HQ Server
DisableProgramGroupPage=yes
PrivilegesRequired=admin
OutputDir=..\..\dist
OutputBaseFilename=IC-WARE-HQ-Server-Setup-{#AppVersion}
SetupIconFile=..\installer\ichq.ico
UninstallDisplayIcon={app}\ichq.ico
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19041

[Languages]
Name: "de"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "energie"; Description: "Energiesparmodus im Netzbetrieb ausschalten (empfohlen — der PC ist jetzt ein Server)"

[Files]
Source: "IchqServer.psm1"; DestDir: "{app}"; Flags: ignoreversion
Source: "einrichten.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "steuerung.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "deinstallieren.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\installer\ichq.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\dist\quelle.tar"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\IC WARE HQ öffnen"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\steuerung.ps1"" -Aktion Oeffnen"; IconFilename: "{app}\ichq.ico"
Name: "{group}\Status"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\steuerung.ps1"" -Aktion Status"; IconFilename: "{app}\ichq.ico"
Name: "{group}\Diagnose (Erreichbarkeit)"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\steuerung.ps1"" -Aktion Diagnose"; IconFilename: "{app}\ichq.ico"
Name: "{group}\Domain ändern"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\steuerung.ps1"" -Aktion Domain"; IconFilename: "{app}\ichq.ico"
Name: "{group}\Cloudflare-Token ändern"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\steuerung.ps1"" -Aktion Token"; IconFilename: "{app}\ichq.ico"
Name: "{group}\Erste Firma anlegen"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\steuerung.ps1"" -Aktion ErsteFirma"; IconFilename: "{app}\ichq.ico"
Name: "{group}\Sicherung jetzt + Wiederherstellungstest"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\steuerung.ps1"" -Aktion Sicherung"; IconFilename: "{app}\ichq.ico"
Name: "{group}\Betriebsprüfung"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\steuerung.ps1"" -Aktion Pruefung"; IconFilename: "{app}\ichq.ico"
Name: "{group}\Logs"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\steuerung.ps1"" -Aktion Logs"; IconFilename: "{app}\ichq.ico"
Name: "{group}\Server starten"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\steuerung.ps1"" -Aktion Starten"; IconFilename: "{app}\ichq.ico"
Name: "{group}\Server stoppen"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\steuerung.ps1"" -Aktion Stoppen"; IconFilename: "{app}\ichq.ico"
Name: "{group}\Externe Sicherung (S3) einrichten"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\steuerung.ps1"" -Aktion SicherungExtern"; IconFilename: "{app}\ichq.ico"
Name: "{group}\E-Mail-Versand einrichten"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\steuerung.ps1"" -Aktion EMail"; IconFilename: "{app}\ichq.ico"
Name: "{group}\Einrichtung wiederholen"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\steuerung.ps1"" -Aktion Einrichten"; IconFilename: "{app}\ichq.ico"
Name: "{autodesktop}\IC WARE HQ"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\steuerung.ps1"" -Aktion Oeffnen"; IconFilename: "{app}\ichq.ico"

[Code]
var
  SeiteDomain: TInputQueryWizardPage;
  SeiteToken: TInputQueryWizardPage;
  Ergebnis: Integer;
  Update: Boolean;

function Erlaubt(S, Zeichen: String): Boolean;
var I: Integer;
begin
  Result := Length(S) > 0;
  for I := 1 to Length(S) do
    if Pos(S[I], Zeichen) = 0 then Result := False;
end;

function DomainOk(S: String): Boolean;
begin
  Result := Erlaubt(S, 'abcdefghijklmnopqrstuvwxyz0123456789.-') and (Pos('.', S) > 1) and (S[1] <> '-');
end;

function EmailOk(S: String): Boolean;
begin
  Result := Erlaubt(S, 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_+%@') and (Pos('@', S) > 1);
end;

function LetztesWort(S: String): String;
var P: Integer;
begin
  S := Trim(S);
  P := Length(S);
  while (P > 0) and (S[P] <> ' ') do P := P - 1;
  Result := Copy(S, P + 1, Length(S));
end;

function TokenOk(S: String): Boolean;
begin
  Result := Erlaubt(S, 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+/_=-') and (Length(S) >= 80);
end;

procedure InitializeWizard();
begin
  Update := RegKeyExists(HKLM, 'SOFTWARE\IC WARE HQ Server');
  SeiteDomain := CreateInputQueryPage(wpSelectTasks, 'Adresse im Internet',
    'Unter welcher Adresse sollen alle Nutzer IC WARE HQ erreichen?',
    'Die Domain muss in Ihrem Cloudflare-Konto verwaltet sein (kostenloser Tarif genügt). ' +
    'Beispiel: hq.meine-firma.de. Ändern geht später über Startmenü → „Domain ändern".');
  SeiteDomain.Add('Domain:', False);
  SeiteDomain.Add('Ihre E-Mail-Adresse (Betreiber, für Warnungen):', False);
  SeiteDomain.Values[0] := ExpandConstant('{param:DOMAIN|}');
  SeiteDomain.Values[1] := ExpandConstant('{param:EMAIL|}');
  SeiteToken := CreateInputQueryPage(SeiteDomain.ID, 'Cloudflare-Tunnel',
    'Token des Tunnels aus Cloudflare',
    'dash.cloudflare.com → Zero Trust → Networks → Tunnels → „Create a tunnel" (Cloudflared) → Namen vergeben → ' +
    'den angezeigten Befehl kopieren und hier einfügen (das Token wird herausgelöst). Danach dort unter ' +
    '„Public Hostname" Ihre Domain mit Dienst HTTP und Adresse caddy:80 eintragen.' + #13#10#13#10 +
    'Bei einem Update leer lassen = bisheriges Token bleibt.');
  SeiteToken.Add('Token oder Befehl:', True);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var T: String;
begin
  Result := True;
  if CurPageID = SeiteDomain.ID then begin
    SeiteDomain.Values[0] := Lowercase(Trim(SeiteDomain.Values[0]));
    if not DomainOk(SeiteDomain.Values[0]) then begin
      MsgBox('Bitte nur den Hostnamen eingeben, z. B. hq.meine-firma.de (ohne https:// und ohne Pfad).', mbError, MB_OK);
      Result := False;
    end else if not EmailOk(Trim(SeiteDomain.Values[1])) then begin
      MsgBox('Bitte eine gültige E-Mail-Adresse eingeben.', mbError, MB_OK);
      Result := False;
    end;
  end;
  if CurPageID = SeiteToken.ID then begin
    T := LetztesWort(SeiteToken.Values[0]);
    if (T = '') and not Update then begin
      MsgBox('Für die Ersteinrichtung wird das Tunnel-Token benötigt.', mbError, MB_OK);
      Result := False;
    end else if (T <> '') and not TokenOk(T) then begin
      MsgBox('Das sieht nicht wie ein Cloudflare-Tunnel-Token aus.', mbError, MB_OK);
      Result := False;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  TokenDatei, Parameter, T: String;
begin
  if CurStep <> ssPostInstall then Exit;
  T := LetztesWort(SeiteToken.Values[0]);
  if (T = '') and (ExpandConstant('{param:TOKENFILE|}') <> '') then
    if LoadStringFromFile(ExpandConstant('{param:TOKENFILE|}'), T) then T := LetztesWort(T);
  Parameter := '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\einrichten.ps1') + '"' +
    ' -Domain "' + SeiteDomain.Values[0] + '" -Email "' + Trim(SeiteDomain.Values[1]) + '"' +
    ' -Quelle "' + ExpandConstant('{app}\quelle.tar') + '"';
  if TokenOk(T) then begin
    { Token nie als Argument (Prozessliste): Datei im privaten Setup-Temp-Ordner, einrichten.ps1 löscht sie }
    TokenDatei := ExpandConstant('{tmp}\token.txt');
    SaveStringToFile(TokenDatei, T, False);
    Parameter := Parameter + ' -TokenDatei "' + TokenDatei + '"';
  end;
  if WizardIsTaskSelected('energie') then Parameter := Parameter + ' -EnergieAus';
  WizardForm.StatusLabel.Caption := 'IC WARE HQ wird eingerichtet (10–20 Minuten, Fortschritt im Konsolenfenster) …';
  if not Exec('powershell.exe', Parameter, '', SW_SHOW, ewWaitUntilTerminated, Ergebnis) then Ergebnis := -1;
  DeleteFile(ExpandConstant('{tmp}\token.txt'));
  if (Ergebnis <> 0) and (Ergebnis <> 3010) then
    SuppressibleMsgBox('Die Einrichtung ist nicht vollständig (Code ' + IntToStr(Ergebnis) + '). Protokoll: ' +
      ExpandConstant('{commonappdata}\IC-WARE-HQ\einrichten.log') + #13#10 +
      'Nach dem Beheben: Startmenü → IC WARE HQ Server → „Einrichtung wiederholen".', mbError, MB_OK, IDOK);
end;

function NeedRestart(): Boolean;
begin
  Result := (Ergebnis = 3010);   { WSL frisch installiert: nach dem Neustart geht die Einrichtung automatisch weiter }
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Code: Integer;
  Parameter: String;
begin
  if CurUninstallStep <> usUninstall then Exit;
  Parameter := '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\deinstallieren.ps1') + '"';
  if (not UninstallSilent()) and (MsgBox('Sollen auch ALLE DATEN gelöscht werden (Datenbank, Dokumente, Einstellungen)?' +
      #13#10#13#10 + 'Nein (empfohlen): Daten bleiben erhalten, eine Neuinstallation übernimmt sie.' + #13#10 +
      'Ja: endgültig gelöscht — nur mit einer Sicherung wiederherstellbar.',
      mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES) then
    Parameter := Parameter + ' -DatenLoeschen';
  Exec('powershell.exe', Parameter, '', SW_SHOW, ewWaitUntilTerminated, Code);
end;
