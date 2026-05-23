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
        if (EventFlag(48100000)) {
            $InitializeCommonEvent(0, 90055000, 48105200, 1, 48102200, 48100201);
            $InitializeCommonEvent(0, 90055001, 48105200, 1, 48100201, 48100200);
        }
        if (EventFlag(48100001)) {
            $InitializeCommonEvent(0, 90055000, 48105200, 2, 48102200, 48100201);
            $InitializeCommonEvent(0, 90055001, 48105200, 2, 48100201, 48100200);
        }
    }
    if (IsMapVariation(1)) {
        $InitializeCommonEvent(0, 90035000, 48100200);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015442, 48102200, 48100200);
        $InitializeCommonEvent(0, 99055400, 48102200, 48100200);
        $InitializeCommonEvent(0, 99055300, 48102200, 48100200);
        $InitializeCommonEvent(0, 99055200, 48100200, 48100800, 48100810);
    }
    $InitializeCommonEvent(0, 90065910, 48100200, 48100205, 48100800, 782000, 690047, 48105210, 48100800, 907820000, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90065911, 48100200, 48100800, 782000, 48105210, 48100800, 907820000, 0, 0, 0, 0, 0);
    if (!IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90065900, 48100800, 1, 0, 0, 1050, 782000, 907820000, 48100800);
    }
    $InitializeCommonEvent(0, 90015012, 48105210, 48100200);
    $InitializeCommonEvent(1, 90015012, 0, 48100200);
    $InitializeCommonEvent(0, 90015020, 48100200, 48100800);
    $InitializeCommonEvent(0, 90015008, 48100205, 48100800, 782000, 48100800, 0, 0.6);
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015443, 48102200, 48100800);
        $InitializeCommonEvent(0, 90015023, 48100200, 40, 0, 48105210, 48100800, 907820000, 0, 0, 0, 0);
        $InitializeCommonEvent(0, 90015030, 48100200, 48105210, 40, 782000, 0);
        $InitializeCommonEvent(0, 90015002, 0, 48100200, 48100800, 48105210, 1020, 782000, 110320, 907820000, 48100800);
        $InitializeCommonEvent(0, 90015470, 48102200, 48100200, 48100800, 48105210, 0, 0, 48105210);
        $InitializeCommonEvent(0, 90015446, 48105210, 48100200, 48100800, 48102200);
        $InitializeCommonEvent(0, 90015460, 48102200, 48100800);
        $InitializeCommonEvent(0, 90015460, 48102200, 0);
        $InitializeCommonEvent(0, 90015460, 48102200, 0);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015475, 48102200, 48100800);
        $InitializeCommonEvent(0, 90015475, 48102200, 0);
        $InitializeCommonEvent(0, 90015475, 48102200, 0);
    }
    $InitializeCommonEvent(0, 90035001, 48100800);
    if (1 == 1) {
        $InitializeCommonEvent(0, 90015070, 1056402601, 48100000, 48100300);
        $InitializeCommonEvent(0, 90015070, 1028402600, 48100000, 48100300);
    }
    if (1 == 2) {
        $InitializeCommonEvent(0, 90015070, 1056402602, 48100000, 48100300);
        $InitializeCommonEvent(0, 90015070, 1028402601, 48100000, 48100300);
    }
    if (1 == 3) {
        $InitializeCommonEvent(0, 90015070, 1056402603, 48100000, 48100300);
        $InitializeCommonEvent(0, 90015070, 1028402602, 48100000, 48100300);
    }
    if (2 == 1) {
        $InitializeCommonEvent(0, 90015070, 1056402601, 48100000, 48100301);
        $InitializeCommonEvent(0, 90015070, 1028402600, 48100000, 48100301);
    }
    if (2 == 2) {
        $InitializeCommonEvent(0, 90015070, 1056402602, 48100000, 48100301);
        $InitializeCommonEvent(0, 90015070, 1028402601, 48100000, 48100301);
    }
    if (2 == 3) {
        $InitializeCommonEvent(0, 90015070, 1056402603, 48100000, 48100301);
        $InitializeCommonEvent(0, 90015070, 1028402602, 48100000, 48100301);
    }
});

$Event(48102800, Default, function(chrEntityId, assetEntityId, chrEntityId2, eventFlagId, eventFlagId2, eventFlagId3) {
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

$Event(48102810, Restart, function(chrEntityId, eventFlagId, eventFlagId2, eventFlagId3, nameId, eventFlagId4, eventFlagId5) {
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
    ForceAnimationPlayback(48100800, 20005, false, false, false);
    DisableCharacterHPBarDisplay(chrEntityId);
    DisableCharacterHPBarDisplay(48100801);
    CreateReferredDamagePair(48100801, chrEntityId);
    CreateReferredDamagePair(48100802, chrEntityId);
    EnableCharacterAI(chrEntityId);
    SetNetworkUpdateRate(48100800, true, CharacterUpdateFrequency.AlwaysUpdate);
    DisplayBossHealthBar(Enabled, chrEntityId, 0, nameId);
});
