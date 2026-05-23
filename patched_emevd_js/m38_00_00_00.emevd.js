// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    None
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    $InitializeCommonEvent(0, 90015310, 38000050, 38000051, 1, 38000200, 38000202, 38000203, 38002405, 38002406, 38002407, 38002410, 38002411, 38002412, 38002415, 38002416, 38002417, 38002420, 38002421, 38002422, 38002400);
    $InitializeCommonEvent(0, 90015301, 38005300, 38000200, 38000201, 38000202, 38000203, 1);
    $InitializeCommonEvent(0, 90015306, 38006500);
    $InitializeCommonEvent(0, 90015303, 38002401);
    $InitializeCommonEvent(0, 90015305, 38002430, 38002431, 38002432, 38002433);
    $InitializeCommonEvent(0, 90015304, 38000050, 38000200, 38000202);
    if (1 >= 2) {
        $InitializeCommonEvent(0, 90015304, 38000051, 38000200, 38000203);
    }
    if (940000 == 0) {
        $InitializeCommonEvent(0, 90015000, 0, 38005810, 903620000, 30, 0, 0);
        $InitializeCommonEvent(0, 99055500, 38005810, 15);
        $InitializeCommonEvent(0, 90015030, 0, 38005810, 30, 940000, 0);
    } else {
        $InitializeCommonEvent(0, 90015000, 0, 38005810, 903620000, 30, 0, 0);
        $InitializeCommonEvent(0, 90015030, 0, 38005810, 30, 940000, 0);
    }
    $InitializeCommonEvent(0, 90015002, 0, 0, 38000810, 38005810, 1030, 940000, 11200, 903620000, 38000510);
    $InitializeCommonEvent(0, 90015006, 38001510, 38000510, 38000810, 5);
    $InitializeCommonEvent(0, 90015005, 38001510, 38002810, 38000810);
    GotoIf(S0, Signed(0) != 0);
    GotoIf(S0, 0 != 0);
    Goto(S2);
S0:
    GotoIf(S1, 940000 != 0);
    $InitializeCommonEvent(0, 90015008, 0, 38000810, 940000, 38005810, 0, 0);
    Goto(S2);
S1:
    $InitializeCommonEvent(0, 90015008, 0, 38000810, 940000, 38005810, 0, 0);
S2:
    if (IsMapVariation(0)) {
        $InitializeCommonEvent(0, 90015050, 38000810, 8175);
    }
    if (940000 == 0) {
        $InitializeCommonEvent(0, 90015000, 0, 38000850, 904660320, 30, 0, 0);
        $InitializeCommonEvent(0, 99055500, 38000850, 15);
        $InitializeCommonEvent(0, 90015030, 0, 38000850, 30, 940000, 0);
    } else {
        $InitializeCommonEvent(0, 90015000, 0, 38000850, 904660320, 30, 0, 0);
        $InitializeCommonEvent(0, 90015030, 0, 38000850, 30, 940000, 0);
    }
    $InitializeCommonEvent(0, 90015002, 0, 0, 38000850, 38000850, 1030, 940000, 11200, 904660320, 38000850);
    $InitializeCommonEvent(0, 90015006, 38001550, 38000550, 38000850, 5);
    $InitializeCommonEvent(0, 90015005, 38001550, 38002850, 38000850);
    GotoIf(S3, Signed(0) != 0);
    GotoIf(S3, 0 != 0);
    Goto(S5);
S3:
    GotoIf(S4, 940000 != 0);
    $InitializeCommonEvent(0, 90015008, 0, 38000850, 940000, 38000850, 0, 0);
    Goto(S5);
S4:
    $InitializeCommonEvent(0, 90015008, 0, 38000850, 940000, 38000850, 0, 0);
S5:
    $InitializeCommonEvent(0, 90005251, 38000850, 13, 0, -1);
    if (IsMapVariation(1)) {
        $InitializeCommonEvent(0, 90015050, 38000850, 8175);
    }
    $InitializeCommonEvent(0, 90035280, 38002491, 38000700, 38000701, 38000702, 8060, 0, 38000810, 38000850, 0, 0, 0);
    $InitializeCommonEvent(0, 90035280, 38002491, 38000700, 38000701, 38000702, 80010, 0, 38000810, 38000850, 0, 0, 0);
    $InitializeCommonEvent(0, 90035280, 38002491, 38000700, 38000701, 38000702, 80011, 1, 38000810, 38000850, 0, 0, 0);
    $InitializeCommonEvent(0, 90035281, 38002491, 38000700, 38000701, 38000702, 80011, 38000810, 38000850, 0, 0, 0);
    $InitializeCommonEvent(0, 90035282, 38000490, 38002490, 38000700, 38000701, 38000702, 38000703);
    $InitializeCommonEvent(0, 90035283, 38000490, 38002491, 38001690, 38000700, 38000701, 38000702, 38000704, 38000705, 38000706);
    $InitializeCommonEvent(0, 90035284, 38005490, 38005491, 38000700, 38000702, 38000705, 38000706);
    $InitializeCommonEvent(0, 90035285, 38000490, 38000700, 38000701, 38000702, 38000705, 38000706);
    $InitializeCommonEvent(0, 90035286, 38000490, 38002491, 38000700, 38000701, 38000702, 38000705, 38000706);
    $InitializeCommonEvent(0, 90035288, 38002491, 38000700, 38000702, 38000705, 38000706);
    $InitializeCommonEvent(0, 90015000, 38000704, 38000490, 907640001, 50, 0, 38000706);
    $InitializeCommonEvent(0, 99055500, 38000490, 15);
    $InitializeCommonEvent(0, 90015025, 8081, 38000704, 38000705, 38000490, 1020, 0, -1, -1, 38000490, 0);
    $InitializeCommonEvent(0, 90085700, 701, 8475, 0, 38000810);
    $InitializeCommonEvent(0, 90085700, 701, 8475, 1, 38000850);
});
