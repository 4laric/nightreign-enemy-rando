// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    DCX_KRAK
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    if (IsMapVariation(0)) {
        if (EventFlag(48400000)) {
            $InitializeCommonEvent(0, 90055000, 48405200, 1, 48402200, 48400201);
            $InitializeCommonEvent(0, 90055001, 48405200, 1, 48400201, 48400200);
        }
        if (EventFlag(48400001)) {
            $InitializeCommonEvent(0, 90055000, 48405200, 2, 48402200, 48400201);
            $InitializeCommonEvent(0, 90055001, 48405200, 2, 48400201, 48400200);
        }
    }
    if (IsMapVariation(1)) {
        $InitializeCommonEvent(0, 90035000, 48400200);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015442, 48402200, 48400200);
        $InitializeCommonEvent(0, 99055400, 48402200, 48400200);
        $InitializeCommonEvent(0, 99055300, 48402200, 48400200);
        $InitializeCommonEvent(0, 99055200, 48400200, 48400800, 48400810);
    }
    $InitializeCommonEvent(0, 90065910, 48400200, 48402205, 48400800, 213001, 690047, 48400800, 48400800, 902130002, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90065911, 48400200, 48400800, 213001, 48400800, 48400800, 902130002, 0, 0, 0, 0, 0);
    if (!IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90065900, 48400800, 2, 0, 0, 1050, 213001, 902130002, 48400800);
    }
    $InitializeCommonEvent(0, 90015012, 48400800, 48400200);
    $InitializeCommonEvent(0, 90015020, 48400200, 48400800);
    $InitializeCommonEvent(0, 90015008, 48402205, 48400800, 213001, 48400800, 16230, 0);
    $InitializeCommonEvent(0, 90065920, 48400800, 7315);
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015443, 48402200, 48400800);
        $InitializeCommonEvent(0, 90015023, 48400200, 40, 0, 48400800, 48400800, 902130002, 0, 0, 0, 0);
        $InitializeCommonEvent(0, 90015030, 48400200, 48400800, 40, 213001, 0);
        $InitializeCommonEvent(0, 90015002, 0, 48400200, 48400800, 48400800, 1020, 213001, 110320, 902130002, 48400800);
        $InitializeCommonEvent(0, 90015470, 48402200, 48400200, 48400800, 48400800, 0, 0, 0);
        $InitializeCommonEvent(0, 90015476, 10002, 48402200);
        $InitializeCommonEvent(0, 90015476, 10003, 48402200);
        $InitializeCommonEvent(0, 90015476, 10004, 48402200);
        $InitializeCommonEvent(0, 90065140, 48400800);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015446, 48400800, 48400200, 48400800, 48402200);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015460, 48402200, 48400800);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015475, 48402200, 48400800);
    }
    $InitializeCommonEvent(0, 90035001, 48400800);
    if (2 == 1) {
        $InitializeCommonEvent(0, 90015070, 1056402601, 48400000, 48400300);
        $InitializeCommonEvent(0, 90015070, 1028402600, 48400000, 48400300);
    }
    if (2 == 2) {
        $InitializeCommonEvent(0, 90015070, 1056402602, 48400000, 48400300);
        $InitializeCommonEvent(0, 90015070, 1028402601, 48400000, 48400300);
    }
    if (2 == 3) {
        $InitializeCommonEvent(0, 90015070, 1056402603, 48400000, 48400300);
        $InitializeCommonEvent(0, 90015070, 1028402602, 48400000, 48400300);
    }
    if (3 == 1) {
        $InitializeCommonEvent(0, 90015070, 1056402601, 48400000, 48400301);
        $InitializeCommonEvent(0, 90015070, 1028402600, 48400000, 48400301);
    }
    if (3 == 2) {
        $InitializeCommonEvent(0, 90015070, 1056402602, 48400000, 48400301);
        $InitializeCommonEvent(0, 90015070, 1028402601, 48400000, 48400301);
    }
    if (3 == 3) {
        $InitializeCommonEvent(0, 90015070, 1056402603, 48400000, 48400301);
        $InitializeCommonEvent(0, 90015070, 1028402602, 48400000, 48400301);
    }
});

$Event(48402800, Default, function(chrEntityId, assetEntityId, chrEntityId2, eventFlagId, eventFlagId2, eventFlagId3) {
    EndIf(EventFlag(eventFlagId));
    EndIf(EventFlag(eventFlagId2));
    WaitFor(HPRatio(chrEntityId) <= 0);
    WaitFixedTimeSeconds(4);
    WaitFor(CharacterDead(chrEntityId));
    DisplayBossHealthBar(Disabled, chrEntityId, 0, 0);
    if (assetEntityId != 0) {
        EnableAsset(assetEntityId);
    }
    if (chrEntityId2 != 0) {
        EnableCharacter(chrEntityId2);
    }
    if (!EventFlag(eventFlagId3)) {
        SetEventFlagID(eventFlagId, ON);
        EndEvent();
    }
    SetEventFlagID(eventFlagId2, ON);
    WaitFor(ElapsedSeconds(3));
    DisableCharacter(chrEntityId);
});

$Event(48402810, Restart, function(chrEntityId, eventFlagId, eventFlagId2, eventFlagId3, nameId, eventFlagId4, eventFlagId5) {
    if (EventFlag(eventFlagId4) || EventFlag(eventFlagId5)) {
        DisableCharacter(chrEntityId);
        DisableCharacterCollision(chrEntityId);
        ForceCharacterDeath(chrEntityId, false);
        EndEvent();
    }
L0:
    DisableCharacter(chrEntityId);
    DisableCharacterCollision(chrEntityId);
    DisableCharacterAI(chrEntityId);
    flag = EventFlag(7515) && (EventFlag(eventFlagId) || EventFlag(eventFlagId2));
    WaitFor((EventFlag(eventFlagId3)) || ElapsedSeconds(90));
    WaitFixedTimeSeconds(1);
    EnableCharacter(chrEntityId);
    EnableCharacterCollision(chrEntityId);
    EnableCharacterAI(chrEntityId);
    ForceAnimationPlayback(48400800, 20005, false, false, false);
    DisableCharacterHPBarDisplay(chrEntityId);
    DisableCharacterHPBarDisplay(48400801);
    CreateReferredDamagePair(48400801, chrEntityId);
    CreateReferredDamagePair(48400802, chrEntityId);
    EnableCharacterAI(chrEntityId);
    SetNetworkUpdateRate(48400800, true, CharacterUpdateFrequency.AlwaysUpdate);
    DisplayBossHealthBar(Enabled, chrEntityId, 0, nameId);
});
