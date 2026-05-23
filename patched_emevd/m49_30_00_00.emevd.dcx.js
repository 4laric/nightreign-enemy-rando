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
        if (EventFlag(49300000)) {
            $InitializeCommonEvent(0, 90055000, 49305200, 1, 49302200, 49300201);
            $InitializeCommonEvent(0, 90055001, 49305200, 1, 49300201, 49300200);
        }
        if (EventFlag(49300001)) {
            $InitializeCommonEvent(0, 90055000, 49305200, 2, 49302200, 49300201);
            $InitializeCommonEvent(0, 90055001, 49305200, 2, 49300201, 49300200);
        }
    }
    if (IsMapVariation(1)) {
        $InitializeCommonEvent(0, 90035000, 49300200);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015442, 49302200, 49300200);
        $InitializeCommonEvent(0, 99055400, 49302200, 49300200);
        $InitializeCommonEvent(0, 99055300, 49302200, 49300200);
        $InitializeCommonEvent(0, 99055200, 49300200, 49300800, 49300810);
    }
    $InitializeCommonEvent(0, 90065910, 49300200, 49300205, 49300800, 921200, 690047, 49305210, 49300800, 904020540, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90065911, 49300200, 49300800, 921200, 49305210, 49300800, 904020540, 0, 0, 0, 0, 0);
    if (!IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90065900, 49300800, 1, 0, 0, 1050, 921200, 904020540, 49300800);
    }
    $InitializeCommonEvent(0, 90015012, 49305210, 49300200);
    $InitializeCommonEvent(1, 90015012, 0, 49300200);
    $InitializeCommonEvent(0, 90015020, 49300200, 49300800);
    $InitializeCommonEvent(0, 90015008, 49300205, 49300800, 921200, 49300800, 46499, 0);
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015443, 49302200, 49300800);
        $InitializeCommonEvent(0, 90015023, 49300200, 40, 0, 49305210, 49300800, 904020540, 0, 0, 0, 0);
        $InitializeCommonEvent(0, 90015030, 49300200, 49305210, 40, 921200, 0);
        $InitializeCommonEvent(0, 90015002, 0, 49300200, 49300800, 49305210, 1020, 921200, 110320, 904020540, 49300800);
        $InitializeCommonEvent(0, 90015470, 49302200, 49300200, 49300800, 49305210, 0, 0, 49305210);
        $InitializeCommonEvent(0, 90015446, 49305210, 49300200, 49300800, 49302200);
        $InitializeCommonEvent(0, 90015460, 49302200, 49300800);
        $InitializeCommonEvent(0, 90015460, 49302200, 0);
        $InitializeCommonEvent(0, 90015460, 49302200, 0);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015475, 49302200, 49300800);
        $InitializeCommonEvent(0, 90015475, 49302200, 0);
        $InitializeCommonEvent(0, 90015475, 49302200, 0);
    }
    $InitializeCommonEvent(0, 90035001, 49300800);
    if (1 == 1) {
        $InitializeCommonEvent(0, 90015070, 1056402601, 49300000, 49300300);
        $InitializeCommonEvent(0, 90015070, 1028402600, 49300000, 49300300);
    }
    if (1 == 2) {
        $InitializeCommonEvent(0, 90015070, 1056402602, 49300000, 49300300);
        $InitializeCommonEvent(0, 90015070, 1028402601, 49300000, 49300300);
    }
    if (1 == 3) {
        $InitializeCommonEvent(0, 90015070, 1056402603, 49300000, 49300300);
        $InitializeCommonEvent(0, 90015070, 1028402602, 49300000, 49300300);
    }
    if (2 == 1) {
        $InitializeCommonEvent(0, 90015070, 1056402601, 49300000, 49300301);
        $InitializeCommonEvent(0, 90015070, 1028402600, 49300000, 49300301);
    }
    if (2 == 2) {
        $InitializeCommonEvent(0, 90015070, 1056402602, 49300000, 49300301);
        $InitializeCommonEvent(0, 90015070, 1028402601, 49300000, 49300301);
    }
    if (2 == 3) {
        $InitializeCommonEvent(0, 90015070, 1056402603, 49300000, 49300301);
        $InitializeCommonEvent(0, 90015070, 1028402602, 49300000, 49300301);
    }
});

$Event(493002800, Default, function(chrEntityId, assetEntityId, chrEntityId2, eventFlagId, eventFlagId2, eventFlagId3) {
    EndIf(EventFlag(eventFlagId));
    EndIf(EventFlag(eventFlagId2));
    WaitFor(HPRatio(chrEntityId) <= 0);
    WaitFixedTimeSeconds(4);
    WaitFor(CharacterDead(chrEntityId));
    DisplayBossHealthBar(Disabled, chrEntityId, 0, 904020540);
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
});

$Event(49302810, Restart, function(chrEntityId, eventFlagId, eventFlagId2, eventFlagId3, nameId, eventFlagId4, eventFlagId5) {
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
    ForceAnimationPlayback(49300800, 20005, false, false, false);
    DisableCharacterHPBarDisplay(chrEntityId);
    DisableCharacterHPBarDisplay(49300801);
    EnableCharacterAI(chrEntityId);
    SetNetworkUpdateRate(49300800, true, CharacterUpdateFrequency.AlwaysUpdate);
    DisplayBossHealthBar(Enabled, chrEntityId, 0, nameId);
});
