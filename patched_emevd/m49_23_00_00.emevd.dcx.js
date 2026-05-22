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
        if (EventFlag(49230000)) {
            $InitializeCommonEvent(0, 90055000, 49235200, 1, 49232200, 49230201);
            $InitializeCommonEvent(0, 90055001, 49235200, 1, 49230201, 49230200);
        }
        if (EventFlag(49230001)) {
            $InitializeCommonEvent(0, 90055000, 49235200, 2, 49232200, 49230201);
            $InitializeCommonEvent(0, 90055001, 49235200, 2, 49230201, 49230200);
        }
    }
    if (IsMapVariation(1)) {
        $InitializeCommonEvent(0, 90035000, 49230200);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015442, 49232200, 49230200);
        $InitializeCommonEvent(0, 99055400, 49232200, 49230200);
        $InitializeCommonEvent(0, 99055300, 49232200, 49230200);
        $InitializeCommonEvent(0, 99055200, 49230200, 49230800, 49230810);
    }
    $InitializeCommonEvent(0, 90065910, 49230200, 49230205, 49230800, 920300, 690048, 49235210, 49230800, 904650600, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90065911, 49230200, 49230800, 920300, 49235210, 49230800, 904650600, 0, 0, 0, 0, 0);
    if (!IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90065900, 49230800, 2, 0, 0, 1050, 920300, 904650600, 49230800);
    }
    $InitializeCommonEvent(0, 90015012, 49235210, 49230200);
    $InitializeCommonEvent(1, 90015012, 0, 49230200);
    $InitializeCommonEvent(0, 90015020, 49230200, 49230800);
    $InitializeCommonEvent(0, 90015008, 49230205, 49230800, 920300, 49230800, 13201, 0);
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015443, 49232200, 49230800);
        $InitializeCommonEvent(0, 90015023, 49230200, 40, 0, 49235210, 49230800, 904650600, 0, 0, 0, 0);
        $InitializeCommonEvent(0, 90015030, 49230200, 49235210, 40, 920300, 0);
        $InitializeCommonEvent(0, 90015002, 0, 49230200, 49230800, 49235210, 1020, 920300, 110320, 904650600, 49230800);
        $InitializeCommonEvent(0, 90015470, 49232200, 49230200, 49230800, 49235210, 0, 0, 49235210);
        $InitializeCommonEvent(0, 90015446, 49235210, 49230200, 49230800, 49232200);
        $InitializeCommonEvent(0, 90015460, 49232200, 49230800);
        $InitializeCommonEvent(0, 90015460, 49232200, 0);
        $InitializeCommonEvent(0, 90015460, 49232200, 0);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015475, 49232200, 49230800);
        $InitializeCommonEvent(0, 90015475, 49232200, 0);
        $InitializeCommonEvent(0, 90015475, 49232200, 0);
    }
    $InitializeCommonEvent(0, 90035001, 49230800);
    if (2 == 1) {
        $InitializeCommonEvent(0, 90015070, 1056402601, 49230000, 49230300);
        $InitializeCommonEvent(0, 90015070, 1028402600, 49230000, 49230300);
    }
    if (2 == 2) {
        $InitializeCommonEvent(0, 90015070, 1056402602, 49230000, 49230300);
        $InitializeCommonEvent(0, 90015070, 1028402601, 49230000, 49230300);
    }
    if (2 == 3) {
        $InitializeCommonEvent(0, 90015070, 1056402603, 49230000, 49230300);
        $InitializeCommonEvent(0, 90015070, 1028402602, 49230000, 49230300);
    }
    if (3 == 1) {
        $InitializeCommonEvent(0, 90015070, 1056402601, 49230000, 49230301);
        $InitializeCommonEvent(0, 90015070, 1028402600, 49230000, 49230301);
    }
    if (3 == 2) {
        $InitializeCommonEvent(0, 90015070, 1056402602, 49230000, 49230301);
        $InitializeCommonEvent(0, 90015070, 1028402601, 49230000, 49230301);
    }
    if (3 == 3) {
        $InitializeCommonEvent(0, 90015070, 1056402603, 49230000, 49230301);
        $InitializeCommonEvent(0, 90015070, 1028402602, 49230000, 49230301);
    }
});

$Event(49232800, Default, function(chrEntityId, assetEntityId, chrEntityId2, eventFlagId, eventFlagId2, eventFlagId3) {
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

$Event(49232810, Restart, function(chrEntityId, eventFlagId, eventFlagId2, eventFlagId3, nameId, eventFlagId4, eventFlagId5) {
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
    ForceAnimationPlayback(48600800, 20005, false, false, false);
    DisableCharacterHPBarDisplay(chrEntityId);
    EnableCharacterAI(chrEntityId);
    SetNetworkUpdateRate(48600800, true, CharacterUpdateFrequency.AlwaysUpdate);
    DisplayBossHealthBar(Enabled, chrEntityId, 0, nameId);
});
